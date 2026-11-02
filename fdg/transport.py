import codecs
import json


class JsonStream:
    """Decode fragmented UTF-8 and concatenated/newline/NUL-delimited JSON objects."""
    def __init__(self):
        self.utf8 = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""

    def feed(self, chunk):
        self.buffer += self.utf8.decode(chunk)
        result = []
        while True:
            self.buffer = self.buffer.lstrip("\x00\r\n\t \ufeff")
            if not self.buffer:
                break
            try:
                message, end = json.JSONDecoder().raw_decode(self.buffer)
            except json.JSONDecodeError:
                if len(self.buffer) > 8 * 1024 * 1024:
                    raise ValueError("Invalid or oversized JSON stream; inspect wire capture")
                break
            original, self.buffer = self.buffer[:end], self.buffer[end:]
            # The live Windows exporter serializes Data a second time.
            if isinstance(message, dict) and isinstance(message.get("Data"), str):
                try:
                    message["Data"] = json.loads(message["Data"])
                except json.JSONDecodeError as exc:
                    raise ValueError("Invalid JSON inside event Data") from exc
            if isinstance(message, dict) and isinstance(message.get("Data"), dict):
                result.append((message, original))
        return result


def read_capture(path):
    """Read complete messages, including a capture whose writer is still open."""
    import gzip
    stream = JsonStream()
    with gzip.open(path, "rb") as source:
        while True:
            try:
                chunk = source.read1(65536)
            except EOFError:
                break  # A running/abruptly closed writer may not have a gzip footer.
            if not chunk:
                break
            yield from stream.feed(chunk)
