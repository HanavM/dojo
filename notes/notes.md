# Dojo lessons

- Immediately use Restore on any host with privileged compromise to clear it and stop penalties.
- Do not use Remove on a host with privileged compromise, as it does not remove root access and wastes a step.
- Do not Restore a host with only user-level compromise unless it escalates to privileged access, as the cost outweighs the penalty.
- Deploy DecoySSHD early on Op_Server0 to prevent Red from gaining access.
- Avoid repeatedly using Analyse or DecoySSHD on the same host, as these actions do not stack or provide new benefits.
- Use DecoySSHD on unscanned hosts to prevent future exploitation, rather than on hosts already being scanned or compromised.
