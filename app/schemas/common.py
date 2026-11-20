"""Constants shared by the request schemas."""

# Identifiers appear in URLs and in log lines, so allow only characters that
# are safe in both: letters, digits, dot, underscore and hyphen.
ID_PATTERN = r"^[A-Za-z0-9._-]+$"