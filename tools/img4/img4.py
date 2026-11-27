"""IMG4 container assembly and parsing — the R13 reconstruction primitive.

R13 (FINDINGS.md:6171-6197, verified) showed that a saved APTicket (IM4M) plus
the PUBLIC stock .im4p payloads reconstruct Apple's installed, personalised boot
files BYTE-FOR-BYTE — no Apple server, no secret. The reconstruction is pure DER
assembly:

    IMG4 ::= SEQUENCE {
        "IMG4"   IA5String,
        im4p     IM4P,                 -- the public payload, verbatim
        im4m     [0] EXPLICIT IM4M,    -- the device's saved APTicket
        im4r     [1] EXPLICIT IM4R     -- OPTIONAL
    }

The 37-byte rule (FINDINGS.md:6195, verified): FILESYSTEM images (kernelcache,
devicetree, sep-firmware, StaticTrustCache) OMIT the [1] IM4R; FIRMWARE-PARTITION
images (disk2/disk3: iBoot, LLB) carry [1] IM4R with BNCN. In this tool that is
simply whether `im4r` is supplied.

Inputs are treated as opaque, already-DER-encoded objects: an .im4p file is a
complete IM4P object, an APTicket .im4m file is a complete IM4M object. We never
need to parse their internals to wrap them, which is why no ASN.1 library is
required.
"""
from __future__ import annotations

from . import der

MAGIC = "IMG4"


def build_img4(im4p: bytes, im4m: bytes | None = None, im4r: bytes | None = None) -> bytes:
    """Assemble an IMG4 container from a payload and optional manifest/restore.

    `im4p` is a complete IM4P object (public payload). `im4m` is a complete IM4M
    object (the APTicket). `im4r` is a complete IM4R object; supply it only for
    firmware-partition images (the 37-byte rule). Returns the DER-encoded IMG4.
    """
    if not im4p:
        raise ValueError("im4p payload is required")
    body = der.ia5string(MAGIC) + im4p
    if im4m is not None:
        body += der.explicit(0, im4m)
    if im4r is not None:
        body += der.explicit(1, im4r)
    return der.tlv(der.TAG_SEQUENCE, body)


def parse_img4(data: bytes) -> dict:
    """Decompose an IMG4 into its parts.

    Returns {"im4p": bytes, "im4m": bytes|None, "im4r": bytes|None}, where im4p
    is the full IM4P object bytes and im4m/im4r are the inner objects (unwrapped
    from their explicit context tags). build_img4(**parse_img4(x)) == x.
    """
    tag, body, _ = der.read_tlv(data)
    if tag != der.TAG_SEQUENCE:
        raise ValueError("IMG4 must be a SEQUENCE")

    offset = 0
    tag, value, offset = der.read_tlv(body, offset)
    if tag != der.TAG_IA5STRING or value != MAGIC.encode("ascii"):
        raise ValueError("not an IMG4 container (missing 'IMG4' marker)")

    tag, value, offset = der.read_tlv(body, offset)
    if tag != der.TAG_SEQUENCE:
        raise ValueError("expected IM4P payload after the 'IMG4' marker")
    result: dict = {"im4p": der.tlv(tag, value), "im4m": None, "im4r": None}

    while offset < len(body):
        tag, value, offset = der.read_tlv(body, offset)
        if tag == der.TAG_CONTEXT_CONSTRUCTED | 0:
            result["im4m"] = value
        elif tag == der.TAG_CONTEXT_CONSTRUCTED | 1:
            result["im4r"] = value
        else:
            raise ValueError(f"unexpected tag {tag:#04x} in IMG4")
    return result


def to_filesystem_image(data: bytes) -> bytes:
    """Return the IMG4 with any [1] IM4R stripped (the filesystem-image form).

    This is the 37-byte-rule transform: it turns a firmware-partition IMG4 into
    the form Apple writes for filesystem images (kernelcache etc.).
    """
    parts = parse_img4(data)
    return build_img4(parts["im4p"], parts["im4m"], im4r=None)
