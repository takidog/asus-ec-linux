package PVE::LocalThermal;
use strict;
use warnings;
use JSON qw(decode_json);
use Fcntl qw(O_RDONLY O_NONBLOCK O_NOFOLLOW S_ISREG);

sub fan_cache {
    my ($path, $now) = @_;
    $path //= '/run/asus-ec-fan/status.json';
    $now //= time();
    my $unavailable = { available => JSON::false, control_supported => JSON::false };
    # Nonblocking, bounded, regular-file read. No EC access or child processes.
    sysopen(my $fh, $path, O_RDONLY | O_NONBLOCK | O_NOFOLLOW) or return $unavailable;
    my @stat = stat($fh);
    if (!@stat || !S_ISREG($stat[2]) || $stat[7] > 4096) {
        close($fh);
        return $unavailable;
    }
    my $data = '';
    my $size = sysread($fh, $data, 4097);
    close($fh);
    return $unavailable if !defined($size) || $size > 4096;
    my $value = eval { decode_json($data) };
    return $unavailable if $@ || ref($value) ne 'HASH';
    for my $key (qw(updated_at fan_rpm mode_raw)) {
        return $unavailable if !defined($value->{$key}) || ref($value->{$key}) || $value->{$key} !~ /^\d+(?:\.\d+)?$/;
    }
    my $age = $now - $value->{updated_at};
    return { %$unavailable, reason => 'stale' } if $age < -5 || $age >= 15;
    my %modes = (0 => 'normal', 1 => 'quiet', 240 => 'full-speed');
    return $unavailable if $value->{fan_rpm} > 65535 || !defined($modes{$value->{mode_raw}})
        || ($value->{mode} // '') ne $modes{$value->{mode_raw}}
        || ($value->{profile} // '') ne 'asus-ite8225-vc66-c2-1602';
    return {
        available => JSON::true,
        control_supported => $value->{mode_raw} == 1 ? JSON::false : JSON::true,
        updated_at => 0 + $value->{updated_at}, age_seconds => $age < 0 ? 0 : $age,
        fan_rpm => 0 + $value->{fan_rpm}, mode => $value->{mode},
    };
}

# Read existing kernel hwmon attributes only. Never probe or write hardware.
sub read_line {
    my ($path) = @_;
    open(my $fh, '<', $path) or return undef;
    my $value = <$fh>;
    close($fh);
    return undef if !defined($value);
    chomp($value);
    return $value;
}

sub temperature {
    my ($path) = @_;
    my $v = read_line($path);
    return undef if !defined($v) || $v !~ /^-?\d+$/;
    $v /= 1000;
    return undef if $v < -100 || $v > 200;
    return $v;
}

sub collect {
    my ($root, $cache) = @_;
    $root //= '/sys/class/hwmon';
    my $out = { map { $_ => [] } qw(cpu cores nvme sata acpi fans) };
    for my $h (sort glob("$root/hwmon*")) {
        my $name = read_line("$h/name") // '';
        my $device = readlink("$h/device") // '';
        my $disk = '';
        if ($name eq 'drivetemp') {
            my @blocks = glob("$h/device/block/*");
            ($disk) = ($blocks[0] // '') =~ m{([^/]+)$};
            $disk //= '';
        }
        if ($name =~ /^(coretemp|nvme|drivetemp|acpitz)$/) {
            for my $f (sort glob("$h/temp*_input")) {
                my $base = $f;
                $base =~ s/_input$//;
                my $value = temperature($f);
                next if !defined($value);
                my $label = read_line("${base}_label") // 'Temperature';
                my $group;
                if ($name eq 'coretemp') {
                    $group = $label =~ /^Core / ? 'cores' : 'cpu';
                } elsif ($name eq 'nvme') {
                    $group = 'nvme';
                    my ($controller) = $device =~ m{(nvme\d+)$};
                    $label = ($controller // 'NVMe') . " $label";
                } elsif ($name eq 'drivetemp') {
                    $group = 'sata';
                    $label = $disk || 'SATA';
                } else {
                    $group = 'acpi';
                    $label = 'ACPI zone';
                }
                my $item = { label => $label, value => $value };
                for my $limit (qw(max crit)) {
                    my $v = temperature("${base}_$limit");
                    $item->{$limit} = $v if defined($v);
                }
                push @{$out->{$group}}, $item;
            }
        }
        for my $f (sort glob("$h/fan*_input")) {
            my $v = read_line($f);
            next if !defined($v) || $v !~ /^\d+$/;
            my $base = $f;
            $base =~ s/_input$//;
            my $label = read_line("${base}_label") // $name;
            push @{$out->{fans}}, { label => $label, value => 0 + $v };
        }
    }
    @{$out->{sata}} = sort { $a->{label} cmp $b->{label} } @{$out->{sata}};
    $out->{ecfan} = fan_cache($cache);
    return $out;
}

1;
