use strict;
use warnings;
use File::Temp qw(tempdir);
use File::Path qw(make_path);
use FindBin;
use Test::More;
use JSON qw(encode_json);
use POSIX qw(mkfifo);
require "$FindBin::Bin/../pve/LocalThermal.pm";

my $root = tempdir(CLEANUP => 1);
sub put {
    my ($path, $value) = @_;
    open(my $fh, '>', "$root/$path") or die $!;
    print $fh "$value\n";
    close($fh);
}
make_path(map { "$root/$_" } qw(hwmon19 hwmon2 hwmon8 hwmon3 hwmon5/device/block/sda));
put('hwmon19/name', 'coretemp');
put('hwmon19/temp1_label', 'Package id 0');
put('hwmon19/temp1_input', '81500');
put('hwmon19/temp1_max', '84000');
put('hwmon19/temp2_label', 'Core 0');
put('hwmon19/temp2_input', '78000');
put('hwmon19/temp3_input', 'invalid');
put('hwmon2/name', 'nvme');
put('hwmon2/temp1_input', '65850');
put('hwmon2/temp1_crit', '84850');
put('hwmon8/name', 'iwlwifi_1');
put('hwmon8/temp1_input', '');
put('hwmon3/name', 'asus');
put('hwmon5/name', 'drivetemp');
put('hwmon5/temp1_input', '51000');
my $s = PVE::LocalThermal::collect($root);
is($s->{cpu}[0]{value}, 81.5, 'CPU found independently of hwmon index');
is($s->{cpu}[0]{max}, 84, 'threshold preserves units');
is(scalar @{$s->{cores}}, 1, 'bad reading omitted');
is($s->{nvme}[0]{value}, 65.85, 'NVMe precision');
is($s->{nvme}[0]{crit}, 84.85, 'critical threshold');
is($s->{sata}[0]{label}, 'sda', 'SATA block device label');
is($s->{sata}[0]{value}, 51, 'SATA value');
is(scalar @{$s->{fans}}, 0, 'missing RPM is not reported as zero');
put('hwmon3/fan1_input', '1500');
put('hwmon3/fan1_label', 'CPU fan');
is(PVE::LocalThermal::collect($root)->{fans}[0]{value}, 1500, 'RPM detected if exposed later');
unlink "$root/hwmon19/temp1_input";
is(scalar @{PVE::LocalThermal::collect($root)->{cpu}}, 0, 'disappearing sensor omitted');
my $cache = "$root/status.json";
my $reading = { updated_at => 100, fan_rpm => 3250, mode_raw => 0, mode => 'normal',
                profile => 'asus-ite8225-vc66-c2-1602' };
put('status.json', encode_json($reading));
ok(PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'fresh cached fan available');
ok(PVE::LocalThermal::fan_cache($cache, 110)->{control_supported}, 'verified normal mode writable');
is(PVE::LocalThermal::fan_cache($cache, 110)->{fan_rpm}, 3250, 'cached RPM preserved');
ok(!PVE::LocalThermal::fan_cache($cache, 115)->{available}, '15-second old reading rejected');
ok(!PVE::LocalThermal::fan_cache($cache, 90)->{available}, 'future timestamp rejected');
for my $case (
    { %$reading, profile => 'another-board' },
    { %$reading, mode => 'full-speed' },
    { %$reading, fan_rpm => -1 },
    { %$reading, updated_at => [] },
) {
    put('status.json', encode_json($case));
    ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'malformed or incompatible sample rejected');
}
put('status.json', encode_json({ %$reading, mode => 'quiet', mode_raw => 1 }));
ok(!PVE::LocalThermal::fan_cache($cache, 110)->{control_supported}, 'quiet reading cannot enable writes');
put('status.json', '{incomplete');
ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'invalid JSON fails closed');
put('status.json', 'x' x 4097);
ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'oversized cache rejected');
unlink $cache;
symlink "$root/hwmon3/fan1_input", $cache or die $!;
ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'cache symlink rejected');
unlink $cache;
mkfifo($cache, 0600) or die $!;
eval {
    local $SIG{ALRM} = sub { die "FIFO read blocked\n" };
    alarm 2;
    ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'FIFO does not block a status request');
    alarm 0;
};
die $@ if $@;
unlink $cache;
ok(!PVE::LocalThermal::fan_cache($cache, 110)->{available}, 'missing cache fails closed');
done_testing();
