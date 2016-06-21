""" nd command

Executes sub-commands in nd namespace.

"""

from __future__ import print_function

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

from nd_toolbelt import ntp

DEFAULT_NTP_HOST = 'time.apple.com'
CHECK_CLOCK_TIMEOUT = 2  # Only wait for ntp for 2 seconds
MAX_CLOCK_SKEW_TIME = 60  # Time in seconds to tolerate for system clock offset


def parse_args(argv, known_only=True):
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument('--update', action='store_true', dest='force_update',
                              help='Forces update of nd-toolbelt before the given command is run')
    update_group.add_argument('--no-update', action='store_true', dest='skip_update',
                              help='Prevents update of nd-toolbelt before the given command is run')
    parser.add_argument('--update-freq', type=int, default=3600,
                        help='Minimum number of seconds between updates.')

    parser.add_argument('--no-clock-check', action='store_true', dest='skip_clock_check',
                        help='Do not check the system clock.')
    parser.add_argument('--check-clock-freq', type=int, default=3600,
                        help='Minimum number of seconds between clock checks')

    parser.add_argument('command', help='The desired app to run via the nd_toolbelt app!')
    parser.add_argument('args', nargs=argparse.REMAINDER,
                        help='Arguments to pass to the desired app')

    args_with_opts = shlex.split(os.getenv('ND_TOOLBELT_OPTS', '')) + list(argv[1:])

    if known_only:
        return parser.parse_args(args_with_opts)
    else:
        return parser.parse_known_args(args_with_opts)[0]  # Return only known args from tuple


def maybe_reload_with_updates(argv):
    # Allow unknown arguments if they may be present in future versions of nd
    known_args = parse_args(argv, known_only=False)

    if known_args.skip_update:
        return

    nd_toolbelt_root = os.getenv('ND_TOOLBELT_ROOT')

    # Get the repo location from pip if it isn't already defined
    if not nd_toolbelt_root:
        output = subprocess.check_output(
            'pip show nd-toolbelt --disable-pip-version-check', shell=True).decode('utf-8')
        matches = re.search("Location:\s+(/\S+)", output)
        if matches:
            nd_toolbelt_root = matches.group(1)

    if nd_toolbelt_root:
        updated_path = nd_toolbelt_root + '/.updated'

        try:
            updated_creation_date = os.path.getmtime(updated_path)
        except OSError:  # File doesn't exist
            needs_update = True
        else:
            current_time = time.time()
            needs_update = (current_time - updated_creation_date) >= known_args.update_freq

        if needs_update or known_args.force_update:
            subprocess.check_output(['touch', updated_path])
            print('Checking for nd toolbelt updates...', file=sys.stderr)

            branch = subprocess.check_output(
                'git rev-parse --abbrev-ref HEAD', shell=True).decode('utf-8')
            process = subprocess.Popen('git pull origin {}'.format(branch), shell=True,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, close_fds=True)
            output = process.stdout.read().decode('utf-8')
            process.communicate()  # Collect the return code

            if 'Already up-to-date.' not in output and process.returncode == 0:
                # Install the new version
                subprocess.check_output('pip install -e .', shell=True)
                os.execvp('nd', argv)  # Hand off to new nd version
            elif process.returncode != 0:
                print('Unable to update repository.', file=sys.stderr)


def check_system_clock(check_clock_freq, ntp_host=DEFAULT_NTP_HOST,
                       ntp_timeout=CHECK_CLOCK_TIMEOUT):
    clock_checked_path = os.path.join(tempfile.gettempdir(), '.nd_toolbelt_clock_last_checked')
    current_time = time.time()

    try:
        clock_checked_date = os.path.getmtime(clock_checked_path)
    except OSError:  # File doesn't exist
        check_clock = True
    else:
        check_clock = (current_time - clock_checked_date) >= check_clock_freq

    if check_clock:
        print('Checking that the current machine time is accurate...', file=sys.stderr)

        # Time in seconds since 1970 epoch
        system_time = current_time

        try:
            network_time = ntp.get_ntp_time(host=ntp_host, timeout=ntp_timeout)
        except ntp.NtpTimeError as e:
            print('Error checking network time, exception: {}'.format(e), file=sys.stderr)
            return

        time_difference = network_time - system_time

        if abs(time_difference) >= MAX_CLOCK_SKEW_TIME:
            print('The system clock is behind by {} seconds.'
                  ' Please run "sudo ntpdate -u time.apple.com".'.format(time_difference),
                  file=sys.stderr)

        subprocess.check_output(['touch', clock_checked_path])


def main(argv=sys.argv):
    args = parse_args(argv)
    command = 'nd-' + args.command

    try:
        app_path = subprocess.check_output(['which', command]).strip()
    except subprocess.CalledProcessError:
        sys.exit('ERROR: executable "{}" not found'.format(command))

    maybe_reload_with_updates(argv)
    if not args.skip_clock_check:
        check_system_clock(args.check_clock_freq)

    os.execv(app_path, [command] + args.args)

if __name__ == "__main__":
    main(sys.argv)
