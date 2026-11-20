# Test machines (ROADMAP Q.6)

Thoron is checked on machines that go back to a clean state in one step, so that every run starts from a PC
that never had Thoron.

## Windows 11 x64: Windows Sandbox

Windows Sandbox is a clean Windows at every start and is gone when it closes. The checks in `tools/qa/sandbox_*.py`
write a configuration (networking off, no GPU, one folder it may only read and one it writes its findings to)
and a PowerShell script that runs at logon, start the Sandbox and read the findings back. They cover the
installer, the first start, updates while Thoron runs, a portable copy's traces, policies, imports and the
portable passphrase on a new PC. Dialog buttons are found by their IDs, never by their words, because the
Sandbox shows the host's Windows language.

## Ubuntu 24.04 and 26.04 LTS x64: WSL test distributions

Two WSL distributions, `thoron-test-2404` and `thoron-test-2604`, made from Microsoft's store images of
Ubuntu 24.04 and 26.04 LTS. Each has a plain user `tester` who may use sudo, and nothing else installed. Right
after that a clean snapshot of each was exported. `tools/qa/wsl_test_vm.py`:

```powershell
py -3 -I tools/qa/wsl_test_vm.py list --root C:\thoron-build\vm
py -3 -I tools/qa/wsl_test_vm.py restore --root C:\thoron-build\vm --name thoron-test-2404
py -3 -I tools/qa/wsl_test_vm.py run --root C:\thoron-build\vm --name thoron-test-2604 -- <command>
```

`restore` removes the machine and imports its clean snapshot again: one step, about 15 seconds (measured
2026-11-20: a file written into the 26.04 machine was gone after it). The tool only ever touches distributions
whose name starts with `thoron-test-`; a person's own distributions are never named, stopped or changed.

Making them again on another PC:

```powershell
wsl --install Ubuntu-24.04 --name thoron-test-2404 --location C:\thoron-build\vm\thoron-test-2404 --no-launch
wsl --install Ubuntu-26.04 --name thoron-test-2604 --location C:\thoron-build\vm\thoron-test-2604 --no-launch
# as root in each: a user `tester` with sudo, made the default user in /etc/wsl.conf
wsl --export thoron-test-2404 C:\thoron-build\vm\clean\thoron-test-2404.tar
wsl --export thoron-test-2604 C:\thoron-build\vm\clean\thoron-test-2604.tar
```

**What they are not.** WSL has no AppArmor by default, so the AppArmor side of Chromium's Linux sandbox (Ubuntu's
rule for unprivileged user namespaces, P2.9 and S.5) is not what a desktop Ubuntu has; its desktop is WSLg
(Wayland and X11 windows, no GNOME or KDE session and no GNOME keyring unless one is installed for a test). A
check that needs those says so and still needs a full Ubuntu desktop.
