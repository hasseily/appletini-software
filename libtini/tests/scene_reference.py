"""Independent rendering of a libtini scene, for target tests.

render() reads the scene's state and sprite list through read(address,
length) -> bytes of MAIN memory and returns the packed bytes the area must
show: the background, then each listed sprite in order, colour 0 transparent
in images. It shares no code with the 65C02 renderer.
"""


def _word(data, offset=0):
    return data[offset] | data[offset + 1] << 8


def _signed(value):
    return value - 0x10000 if value & 0x8000 else value


def render(read, labels):
    """Return (screen address of the area's first byte, row bytes, rows)."""
    def byte(name):
        return read(labels[name], 1)[0]
    x0, y0 = byte("_ti_scene_x0"), byte("_ti_scene_y0")
    row_bytes, lines = byte("_ti_scene_row_bytes"), byte("_ti_scene_lines")
    background = byte("_ti_scene_fill") & 15
    count = byte("_ti_scene_count")
    arrays = {name: read(labels["_ti_scene_" + name], count) if count else b""
              for name in ("x_lo", "x_hi", "y_lo", "y_hi", "image", "color")}
    images = _word(read(labels["_ti_scene_images"], 2))
    table = read(images, 5 * byte("_ti_scene_image_count"))
    width = row_bytes * 2
    screen = [[background] * width for _ in range(lines)]
    cache = {}
    for i in range(count):
        x = _signed(arrays["x_lo"][i] | arrays["x_hi"][i] << 8) - x0 * 2
        y = _signed(arrays["y_lo"][i] | arrays["y_hi"][i] << 8) - y0
        entry = arrays["image"][i] * 5
        pixels, bytes_, rows, stride = _word(table, entry), table[entry + 2], table[entry + 3], table[entry + 4]
        color = arrays["color"][i] & 15
        if pixels and pixels not in cache:
            cache[pixels] = read(pixels, (rows - 1) * stride + bytes_)
        data = cache.get(pixels)
        for row in range(max(0, -y), min(rows, lines - y)):
            line = screen[y + row]
            for column in range(max(0, -x), min(bytes_ * 2, width - x)):
                if data is None:
                    line[x + column] = color
                else:
                    value = data[row * stride + column // 2]
                    nibble = value >> 4 if column % 2 == 0 else value & 15
                    if nibble:
                        line[x + column] = nibble
    packed = [bytes(line[i] << 4 | line[i + 1] for i in range(0, width, 2)) for line in screen]
    return 0x2000 + y0 * 160 + x0, row_bytes, packed


def mismatch(read, read_aux, labels):
    """None when the screen shows the scene, else a description of the first difference."""
    start, row_bytes, rows = render(read, labels)
    for line, expected in enumerate(rows):
        actual = read_aux(start + line * 160, row_bytes)
        if actual != expected:
            column = next(i for i in range(row_bytes) if actual[i] != expected[i])
            return (f"area line {line} byte {column} is ${actual[column]:02X}, "
                    f"expected ${expected[column]:02X}")
    return None
