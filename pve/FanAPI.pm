package PVE::LocalFanAPI;
use strict;
use warnings;
use PVE::JSONSchema qw(get_standard_option);
use PVE::RPCEnvironment;
use PVE::Tools qw(run_command);
require '/usr/local/share/pve-local-thermal/LocalThermal.pm';

sub register {
    my ($class) = @_;
    $class->register_method({
        name => 'set_local_fan_mode',
        path => 'localfan',
        method => 'PUT',
        proxyto => 'node',
        protected => 1,
        description => 'Select a verified ASUS EC fan mode as a background task.',
        permissions => { check => ['perm', '/nodes/{node}', ['Sys.Modify']] },
        parameters => {
            additionalProperties => 0,
            properties => {
                node => get_standard_option('pve-node'),
                mode => { type => 'string', enum => ['normal', 'full-speed'] },
            },
        },
        returns => { type => 'string' },
        code => sub {
            my ($param) = @_;
            my $cached = PVE::LocalThermal::fan_cache();
            die "Fan readings unavailable or stale; wait for the background monitor.\n"
                if !$cached->{available} || !$cached->{control_supported};
            my $rpcenv = PVE::RPCEnvironment::get();
            my $user = $rpcenv->get_user();
            return $rpcenv->fork_worker('asusfan', $param->{mode}, $user, sub {
                run_command(['/usr/bin/python3',
                    '/usr/local/share/pve-local-thermal/fan-cache.py',
                    'set-mode', $param->{mode}], timeout => 20);
            });
        },
    });
}
1;
