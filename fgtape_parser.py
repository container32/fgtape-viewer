#!/usr/bin/env python3
import sys
import argparse
import json
import gzip
import zlib
import struct
import xml.etree.ElementTree as ET

def parse_xml_node(node):
    """
    Recursively parse an XML node into native Python dicts or basic types.
    Type conversion is performed according to SimGear PropertyList's `type` attribute.
    """
    children = list(node)
    if children:
        d = {}
        for child in children:
            child_val = parse_xml_node(child)
            tag = child.tag
            if tag in d:
                if isinstance(d[tag], list):
                    d[tag].append(child_val)
                else:
                    d[tag] = [d[tag], child_val]
            else:
                d[tag] = child_val
        return d

    val_type = node.get("type", "string")
    text = node.text if node.text is not None else ""
    text_clean = text.strip()

    if val_type == "string":
        return text_clean
    elif val_type in ("int", "int16", "int8", "long"):
        return int(text_clean) if text_clean else 0
    elif val_type in ("double", "float"):
        return float(text_clean) if text_clean else 0.0
    elif val_type == "bool":
        return text_clean.lower() in ("true", "1")
    else:
        return text_clean

def extract_signals(xml_root):
    """
    Extract all signal definitions from the configuration XML,
    supporting nested signal definitions and `%i` index expansion.
    """
    signals_node = xml_root.find(".//signals")
    if signals_node is None:
        return []

    signals = []

    def process_node(node, prefix="", count=1):
        c_count = count
        count_elem = node.find("count")
        if count_elem is not None and count_elem.text:
            try:
                c_count = int(count_elem.text.strip())
            except ValueError:
                pass

        c_prefix = prefix
        prefix_elem = node.find("prefix")
        if prefix_elem is not None and prefix_elem.text:
            p_text = prefix_elem.text.strip()
            if p_text:
                if not p_text.endswith("/"):
                    p_text += "/"
                c_prefix += p_text

        for child in node:
            if child.tag == "signal":
                s_type = child.findtext("type", "float").strip()
                s_interp = child.findtext("interpolation", "linear").strip()
                s_prop = child.findtext("property", "").strip()
                if not s_prop:
                    continue
                full_prop = c_prefix + s_prop
                if "%i" in full_prop:
                    for i in range(c_count):
                        p = full_prop.replace("%i", str(i))
                        signals.append({
                            "type": s_type,
                            "interpolation": s_interp,
                            "property": p
                        })
                else:
                    signals.append({
                        "type": s_type,
                        "interpolation": s_interp,
                        "property": full_prop
                    })
            elif child.tag == "signals":
                process_node(child, c_prefix, c_count)

    process_node(signals_node)
    return signals

def prepare_signals_info(config_root):
    """
    Analyse the signal list in the configuration XML and group it according
    to FlightGear's in-memory alignment order:
    1. double (64-bit)
    2. float (32-bit)
    3. int (32-bit integer)
    4. int16 (16-bit short integer)
    5. int8 (8-bit char)
    6. bool (bit-packed, 8 booleans per byte)
    """
    raw_signals = extract_signals(config_root)
    doubles = [s for s in raw_signals if s["type"] == "double"]
    floats = [s for s in raw_signals if s["type"] == "float"]
    ints = [s for s in raw_signals if s["type"] == "int"]
    int16s = [s for s in raw_signals if s["type"] == "int16"]
    int8s = [s for s in raw_signals if s["type"] == "int8"]
    bools = [s for s in raw_signals if s["type"] == "bool"]
    all_signals = doubles + floats + ints + int16s + int8s + bools

    signals_size = (
        len(doubles) * 8 +
        len(floats) * 4 +
        len(ints) * 4 +
        len(int16s) * 2 +
        len(int8s) * 1 +
        ((len(bools) + 7) // 8)
    )

    # FlightGear 中 record-size 包含了 8 字节的 sim-time 占位
    record_size = signals_size + 8
    rec_size_elem = config_root.find(".//recorder/record-size")
    if rec_size_elem is not None and rec_size_elem.text:
        try:
            record_size = int(rec_size_elem.text.strip())
        except ValueError:
            pass

    return doubles, floats, ints, int16s, int8s, bools, all_signals, record_size

def unpack_frame(frame_raw, doubles, floats, ints, int16s, int8s, bools):
    """
    Unpack the signal data of a single frame according to FlightGear's binary frame layout.
    """
    vals = {}
    pos = 0

    if doubles:
        d_vals = struct.unpack_from(f"<{len(doubles)}d", frame_raw, pos)
        for s, v in zip(doubles, d_vals):
            vals[s["property"]] = v
        pos += len(doubles) * 8

    if floats:
        f_vals = struct.unpack_from(f"<{len(floats)}f", frame_raw, pos)
        for s, v in zip(floats, f_vals):
            vals[s["property"]] = v
        pos += len(floats) * 4

    if ints:
        i_vals = struct.unpack_from(f"<{len(ints)}i", frame_raw, pos)
        for s, v in zip(ints, i_vals):
            vals[s["property"]] = v
        pos += len(ints) * 4

    if int16s:
        h_vals = struct.unpack_from(f"<{len(int16s)}h", frame_raw, pos)
        for s, v in zip(int16s, h_vals):
            vals[s["property"]] = v
        pos += len(int16s) * 2

    if int8s:
        b_vals = struct.unpack_from(f"<{len(int8s)}b", frame_raw, pos)
        for s, v in zip(int8s, b_vals):
            vals[s["property"]] = v
        pos += len(int8s) * 1

    if bools:
        num_bool_bytes = (len(bools) + 7) // 8
        bool_bytes = frame_raw[pos : pos + num_bool_bytes]
        for i, s in enumerate(bools):
            vals[s["property"]] = bool(bool_bytes[i >> 3] & (1 << (i & 7)))
        pos += num_bool_bytes

    return vals

def parse_normal_tape(data):
    """
    Parse a standard Normal-format fgtape (simgear::gzContainer container format).
    """
    pos = 0
    magic = struct.unpack_from("<I", data, pos)[0]
    if magic != 0x11223344:
        raise ValueError(f"Invalid gzContainer magic: {hex(magic)}")
    pos += 4

    meta_dict = {}
    signals_info = None
    has_multiplayer = False
    multiplayer_legacy = False
    frames = []

    n = len(data)
    while pos + 12 <= n:
        c_type, c_size = struct.unpack_from("<iq", data, pos)
        pos += 12

        if c_type == 0:  # Header
            pos += c_size
        elif c_type == 1:  # MetaData
            meta_xml = data[pos : pos + c_size].rstrip(b"\x00")
            pos += c_size
            root = ET.fromstring(meta_xml.decode("utf-8", errors="replace"))
            meta_node = root.find("meta")
            if meta_node is not None:
                meta_dict = parse_xml_node(meta_node)
            for d in root.findall(".//data"):
                if d.text and d.text.strip() == "multiplayer":
                    has_multiplayer = True
            mp_elem = root.find(".//multiplayer")
            if mp_elem is not None and mp_elem.text:
                if mp_elem.text.strip().lower() in ("true", "1"):
                    multiplayer_legacy = True
                    has_multiplayer = True
        elif c_type == 2:  # Properties (信号及录制器配置)
            prop_xml = data[pos : pos + c_size].rstrip(b"\x00")
            pos += c_size
            config_root = ET.fromstring(prop_xml.decode("utf-8", errors="replace"))
            signals_info = prepare_signals_info(config_root)
        elif c_type == 3:  # RawData (原始数据块: short/medium/long term)
            if signals_info is None or c_size <= 0:
                pos += c_size
                continue

            doubles, floats, ints, int16s, int8s, bools, all_signals, record_size = signals_info
            if record_size <= 0:
                pos += c_size
                continue

            count = c_size // record_size
            for _ in range(count):
                if pos + 8 > n:
                    break
                sim_time = struct.unpack_from("<d", data, pos)[0]
                pos += 8

                if pos + record_size > n:
                    break
                frame_raw = data[pos : pos + record_size]
                pos += record_size

                # 跳过多人联机数据块
                if has_multiplayer:
                    if multiplayer_legacy:
                        if pos + 8 > n:
                            break
                        num_msgs = struct.unpack_from("<Q", data, pos)[0]
                        pos += 8
                        for _ in range(num_msgs):
                            if pos + 8 > n:
                                break
                            msg_sz = struct.unpack_from("<Q", data, pos)[0]
                            pos += 8 + msg_sz
                    else:
                        if pos + 4 > n:
                            break
                        mp_len = struct.unpack_from("<I", data, pos)[0]
                        pos += 4 + mp_len

                vals = unpack_frame(frame_raw, doubles, floats, ints, int16s, int8s, bools)
                frames.append((sim_time, vals))
        else:
            pos += c_size

    all_signals = signals_info[6] if signals_info else []
    return meta_dict, all_signals, frames

def parse_continuous_tape(data):
    """
    Parse the FG 2024.1 Continuous recording format.
    """
    magic = b"FlightGear Flight Recorder Tape"
    pos = len(magic)
    if pos < len(data) and data[pos] == 0:
        pos += 1

    buf_len = struct.unpack_from("<I", data, pos)[0]
    pos += 4
    xml_data = data[pos : pos + buf_len].rstrip(b"\x00")
    pos += buf_len

    root = ET.fromstring(xml_data.decode("utf-8", errors="replace"))
    meta_node = root.find("meta")
    meta_dict = parse_xml_node(meta_node) if meta_node is not None else {}

    signals_info = prepare_signals_info(root)
    doubles, floats, ints, int16s, int8s, bools, all_signals, record_size = signals_info

    compression = 0
    if meta_node is not None:
        comp_elem = meta_node.find("continuous-compression")
        if comp_elem is not None and comp_elem.text:
            try:
                compression = int(comp_elem.text.strip())
            except ValueError:
                pass

    datas = [d.text.strip() for d in root.findall("data") if d.text]

    frames = []
    n = len(data)
    while pos < n:
        if pos + 8 > n:
            break
        sim_time = struct.unpack_from("<d", data, pos)[0]
        pos += 8

        frame_raw = None
        if compression:
            if pos + 5 > n:
                break
            flags = data[pos]
            pos += 1
            has_signals = bool(flags & 1)
            comp_size = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            if pos + comp_size > n:
                break
            comp_data = data[pos : pos + comp_size]
            pos += comp_size
            if has_signals:
                decomp = zlib.decompress(comp_data)
                frame_raw = decomp[:record_size]
        else:
            for d_type in datas:
                if pos + 4 > n:
                    break
                length = struct.unpack_from("<I", data, pos)[0]
                pos += 4
                if pos + length > n:
                    break
                data_payload = data[pos : pos + length]
                pos += length
                if d_type == "signals" and length > 0:
                    frame_raw = data_payload[:record_size]

        if frame_raw is not None:
            vals = unpack_frame(frame_raw, doubles, floats, ints, int16s, int8s, bools)
            frames.append((sim_time, vals))

    return meta_dict, all_signals, frames

def parse_fgtape(raw_bytes):
    """
    Parse the byte stream of a .fgtape file, automatically handling gzip
    decompression and recognising Normal/Continuous formats.
    Returns a dictionary containing `meta`, `signals`, and `data`.
    """
    # 自动处理 gzip 压缩
    if raw_bytes.startswith(b"\x1f\x8b"):
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except Exception:
            pass

    # 判断录像文件类型
    if raw_bytes.startswith(b"\x44\x33\x22\x11"):
        meta_dict, all_signals, frames = parse_normal_tape(raw_bytes)
    elif raw_bytes.startswith(b"FlightGear Flight Recorder Tape"):
        meta_dict, all_signals, frames = parse_continuous_tape(raw_bytes)
    else:
        raise ValueError("Unrecognized file format: neither normal nor continuous fgtape magic found.")

    # 按仿真时间由小到大排序，合并多分辨率缓存并去重
    frames.sort(key=lambda f: f[0])
    deduped_frames = []
    last_t = None
    for f in frames:
        if last_t is None or f[0] != last_t:
            deduped_frames.append(f)
            last_t = f[0]

    # 构建返回的数据字典
    data_dict = {"/sim-time": []}
    for s in all_signals:
        data_dict[s["property"]] = []

    for sim_time, vals in deduped_frames:
        data_dict["/sim-time"].append(sim_time)
        for s in all_signals:
            prop = s["property"]
            data_dict[prop].append(vals.get(prop, None))

    return {
        "meta": meta_dict,
        "signals": all_signals,
        "data": data_dict
    }

def main():
    parser = argparse.ArgumentParser(
        description="Parse FlightGear recording files (.fgtape) and output JSON."
    )
    parser.add_argument("input_file", help="Path to the input .fgtape file.")
    parser.add_argument(
        "-o", "--output", help="Path to the output JSON file (outputs to stdout if omitted)."
    )
    parser.add_argument(
        "--indent", type=int, default=2, 
        help="Number of spaces for JSON indentation (default: 2). Use --indent 0 to disable indents."
    )

    args = parser.parse_args()
    indent = args.indent if args.indent != 0 else None

    try:
        with open(args.input_file, "rb") as f:
            raw_bytes = f.read()
    except Exception as e:
        sys.stderr.write(f"Failed to read file: {e}\n")
        sys.exit(1)

    result = parse_fgtape(raw_bytes)
    json_str = json.dumps(result, indent=indent, ensure_ascii=False)

    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_str)
        except Exception as e:
            sys.stderr.write(f"Failed to write output file: {e}\n")
            sys.exit(1)
    else:
        print(json_str)

if __name__ == "__main__": main()
