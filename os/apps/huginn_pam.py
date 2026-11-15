"""Checking a person's own password through PAM, for Huginn's lock screen in its own compositor's session (KDE's
screen locker does this itself in the KWin session). It runs as the person, not root: pam_unix then asks its small
setgid helper, unix_chkpwd, which only ever answers for the person who's asking.

    check(user, password, service="huginn-lock") → (ok: bool, message: str)

Uses libpam through ctypes, so nothing has to be installed beyond PAM itself. The service is /etc/pam.d/huginn-lock.
"""
import ctypes
import ctypes.util
import threading

PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON, PAM_ERROR_MSG, PAM_TEXT_INFO = 1, 2, 3, 4
PAM_SUCCESS, PAM_AUTH_ERR, PAM_REFRESH_CRED = 0, 7, 0x0010
SAYS = {7: "Wrong password.", 9: "The password can't be checked right now.", 10: "That user can't be checked here.",
        13: "This account has expired.", 12: "This account isn't allowed to sign in now.", 20: "The password has expired."}


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(PamMessage)),
                        ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV), ("appdata_ptr", ctypes.c_void_p)]


_lib = None
_lock = threading.Lock()


def _libs():
    global _lib
    if _lib is None:
        pam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        libc.calloc.restype = ctypes.c_void_p
        libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        libc.strdup.restype = ctypes.c_void_p
        libc.strdup.argtypes = [ctypes.c_char_p]
        pam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(PamConv), ctypes.POINTER(ctypes.c_void_p)]
        pam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_setcred.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_strerror.argtypes = [ctypes.c_void_p, ctypes.c_int]
        pam.pam_strerror.restype = ctypes.c_char_p
        _lib = (pam, libc)
    return _lib


def check(user: str, password: str, service: str = "huginn-lock") -> tuple:
    """Whether `password` is `user`'s, by PAM (the person's own account rules apply too). Takes about two seconds
    when it's wrong: PAM waits a little on purpose."""
    pam, libc = _libs()
    secret = password.encode("utf-8")
    said = []

    def conv(n, messages, responses, _data):
        replies = libc.calloc(n, ctypes.sizeof(PamResponse))       # PAM frees these itself
        if not replies:
            return 5                                              # PAM_BUF_ERR
        out = ctypes.cast(replies, ctypes.POINTER(PamResponse))
        for i in range(n):
            m = messages[i].contents
            if m.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                out[i].resp = libc.strdup(secret)
            elif m.msg and m.msg_style in (PAM_ERROR_MSG, PAM_TEXT_INFO):
                said.append(m.msg.decode("utf-8", "replace"))
        responses[0] = out
        return PAM_SUCCESS

    handle = ctypes.c_void_p()
    cb = CONV(conv)
    talk = PamConv(cb, None)
    with _lock:                                                    # libpam's modules aren't all thread-safe
        rc = pam.pam_start(service.encode(), user.encode(), ctypes.byref(talk), ctypes.byref(handle))
        if rc != PAM_SUCCESS:
            return False, "The password can't be checked right now."
        try:
            rc = pam.pam_authenticate(handle, 0)
            if rc == PAM_SUCCESS:
                rc = pam.pam_acct_mgmt(handle, 0)
            if rc == PAM_SUCCESS:
                pam.pam_setcred(handle, PAM_REFRESH_CRED)          # renews Kerberos tickets and the like, if any
        finally:
            pam.pam_end(handle, rc)
    if rc == PAM_SUCCESS:
        return True, ""
    return False, SAYS.get(rc, (said[-1] if said else "") or "Wrong password.")


if __name__ == "__main__":                                         # huginn_pam.py USER  (password on stdin)
    import sys
    ok, why = check(sys.argv[1], sys.stdin.readline().rstrip("\n"), *(sys.argv[2:3]))
    print("yes" if ok else "no: " + why)
    sys.exit(0 if ok else 1)
