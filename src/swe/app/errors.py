# the caller isn't allowed to do this to this object
class ForbiddenError(PermissionError):
    pass
