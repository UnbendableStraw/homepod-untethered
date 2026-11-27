"""Minimal DER (ASN.1 Distinguished Encoding Rules) helpers for IMG4 assembly.

This is NOT a general ASN.1 library. It implements exactly what reconstructing
an IMG4 container needs: encode/decode a DER length, read one tag-length-value
triple, and wrap bytes in an explicit context tag. All tags used by IMG4 are
low-tag-number (single byte): SEQUENCE (0x30), IA5String (0x16), and the
context-specific constructed tags [0] (0xA0) and [1] (0xA1).

DER (not BER) is required: definite lengths only, minimal length encoding.
"""
from __future__ import annotations

TAG_SEQUENCE = 0x30
TAG_IA5STRING = 0x16
TAG_CONTEXT_CONSTRUCTED = 0xA0  # [0]; [n] is this | n


def encode_length(n: int) -> bytes:
    """DER definite length. Short form < 0x80, else long form."""
    if n < 0:
        raise ValueError("length cannot be negative")
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    if len(body) > 0x7F:
        raise ValueError("length too large for DER long form")
    return bytes([0x80 | len(body)]) + body


def read_length(data: bytes, offset: int) -> tuple[int, int]:
    """Return (length, offset-after-length)."""
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    num = first & 0x7F
    if num == 0:
        raise ValueError("indefinite length is not valid DER")
    if offset + num > len(data):
        raise ValueError("truncated length field")
    length = int.from_bytes(data[offset : offset + num], "big")
    return length, offset + num


def read_tlv(data: bytes, offset: int = 0) -> tuple[int, bytes, int]:
    """Read one tag-length-value. Return (tag, value_bytes, next_offset).

    Only single-byte (low-tag-number) tags are supported, which is all IMG4
    uses at the levels this tool parses.
    """
    if offset >= len(data):
        raise ValueError("no TLV at offset")
    tag = data[offset]
    if tag & 0x1F == 0x1F:
        raise ValueError("high-tag-number form is not supported")
    length, voff = read_length(data, offset + 1)
    end = voff + length
    if end > len(data):
        raise ValueError("TLV value runs past end of data")
    return tag, data[voff:end], end


def tlv(tag: int, value: bytes) -> bytes:
    """Encode a tag-length-value triple."""
    return bytes([tag]) + encode_length(len(value)) + value


def explicit(tag_number: int, value: bytes) -> bytes:
    """Wrap `value` in an explicit context-specific constructed tag [tag_number]."""
    if not 0 <= tag_number <= 0x1E:
        raise ValueError("context tag number out of supported range")
    return tlv(TAG_CONTEXT_CONSTRUCTED | tag_number, value)


def ia5string(text: str) -> bytes:
    """Encode an IA5String (ASCII)."""
    return tlv(TAG_IA5STRING, text.encode("ascii"))
