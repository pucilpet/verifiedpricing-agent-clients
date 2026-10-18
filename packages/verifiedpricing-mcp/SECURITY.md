# Security reporting

Use a private reporting channel agreed directly with the repository owner.
There is no advertised monitored security mailbox or response-time promise.
Never post actual keys, private configuration or pricing responses publicly;
use synthetic credentials in reproductions.

Security boundaries include byte framing before SDK allocation, serial request
admission, notification bounds, capacity held through cancellation, complete
stdout frames, private credential configuration and HTTPS origin validation.
Source quotes and tool data are untrusted content, never commands to execute.

This is local stdio. It does not provide hosted OAuth, remote credential
forwarding or a shared owner key. The official SDK negotiates the local protocol.
Repeated admitted calls can consume the same REST/CLI/MCP account allowance;
restarting a session does not grant new quota or enable automatic retries.
