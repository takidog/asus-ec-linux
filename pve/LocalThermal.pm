package PVE::LocalThermal;
use strict;
use warnings;

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
    my ($root) = @_;
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
    return $out;
}

1;
