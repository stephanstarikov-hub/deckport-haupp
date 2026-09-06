class VPNError(Exception):
    """Only fixed, credential-free messages may cross the RPC boundary."""


INVALID = "Server configuration is invalid or uses unsupported options"
