import hashlib, struct
DIMS = 384
def embed_text_stub(text: str) -> list[float]:
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed = h * ((DIMS * 4 // len(h)) + 1)
    out=[]
    for i in range(DIMS):
        val = struct.unpack("<I", seed[i*4:(i+1)*4])[0]
        out.append(((val % 2000) - 1000) / 1000.0)
    return out
