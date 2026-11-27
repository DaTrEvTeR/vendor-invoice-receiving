"""Use-case errors as HTTP responses."""

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import exception_handler

from ..services import FindingsError, ServiceError, UploadRejected


def handler(exc, context):
    """400 for a refused upload, 409 for anything the invoice's state does not allow, with the reasons."""
    if isinstance(exc, ObjectDoesNotExist):
        exc = NotFound()
    if isinstance(exc, ServiceError):
        body = {"detail": str(exc), "code": type(exc).__name__}
        if isinstance(exc, FindingsError):
            body["issues"] = [
                {"code": f.code, "kind": f.kind, "message": f.message, "line_no": f.line.line_no if f.line else None}
                for f in exc.findings
            ]
        code = status.HTTP_400_BAD_REQUEST if isinstance(exc, UploadRejected) else status.HTTP_409_CONFLICT
        return Response(body, status=code)
    return exception_handler(exc, context)
