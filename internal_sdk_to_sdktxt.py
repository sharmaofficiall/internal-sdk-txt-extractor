import argparse
import json
import re
from pathlib import Path


TYPE_RE = re.compile(r"^\s*(class|struct)\s+([A-Za-z_]\w+)(?:\s*:\s*public\s+([A-Za-z_]\w+))?\s*$")
FIELD_RE = re.compile(
    r"^\s*(?P<decl>.+?;)\s*//\s*(?P<offset>0x[0-9A-Fa-f]+)\((?P<size>0x[0-9A-Fa-f]+)\)"
)
FUNCTION_RE = re.compile(r"^\s*(?P<decl>.+?\))\s*;\s*$")
CLASS_RE = re.compile(r"^Class:\s+(?P<class_path>.+?)\s*$")
UNKNOWN_PROPERTY_RE = re.compile(
    r"UNKNOWN PROPERTY:\s*(?P<type>[A-Za-z_]\w*)\s+(?P<path>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)"
)


def clean_ue_name(name):
    if len(name) > 1 and name[0] in {"U", "A", "F"} and name[1].isupper():
        return name[1:]
    return name


def clean_type(text):
    text = text.strip()
    text = re.sub(r"\b(class|struct|enum)\s+", "", text)
    text = re.sub(r"\b([UAF])([A-Z]\w*)", lambda m: m.group(2), text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" *", "*").replace(" &", "&")
    return text


def clean_dump_type(text):
    text = text.strip()
    text = re.sub(r"\b(class|struct|enum)\s+", "", text)
    text = re.sub(r"\b([UAF])([A-Z]\w*)", lambda m: m.group(2), text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" *", "*").replace(" &", "&")

    def array_repl(match):
        inner = clean_dump_type(match.group(1))
        return f"{inner}[]"

    def map_repl(match):
        key = clean_dump_type(match.group(1))
        value = clean_dump_type(match.group(2))
        return f"<{key}, {value}>"

    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\bTArray<\s*(.+?)\s*>", array_repl, text)
        text = re.sub(r"\bTMap<\s*(.+?)\s*,\s*(.+?)\s*>", map_repl, text)

    text = re.sub(r"\bTScriptInterface<\s*(.+?)\s*>", lambda m: f"interface class {clean_dump_type(m.group(1))}", text)
    text = re.sub(r"\bTEnumAsByte<\s*(.+?)\s*>", lambda m: f"enum {clean_dump_type(m.group(1))}", text)
    return text


def unknown_property_from_line(line):
    match = UNKNOWN_PROPERTY_RE.search(line)
    if not match:
        return None
    property_path = match.group("path")
    name = property_path.rsplit(".", 1)[-1]
    return match.group("type"), name


def parse_files(files):
    parents = {}
    records = []
    current_raw = None

    for path in files:
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            type_match = TYPE_RE.match(line)
            if type_match:
                _, raw_name, raw_parent = type_match.groups()
                current_raw = raw_name
                parents[raw_name] = raw_parent
                records.append({"kind": "type", "raw": raw_name, "path": path, "line": line_no})
                continue

            if not current_raw:
                continue

            stripped = line.strip()
            if stripped == "};":
                current_raw = None
                continue

            field_match = FIELD_RE.match(line)
            if field_match:
                decl = field_match.group("decl").rstrip(";").strip()
                offset = int(field_match.group("offset"), 16)
                size = int(field_match.group("size"), 16)

                recovered_unknown = unknown_property_from_line(line)
                if "UnknownData" in decl and recovered_unknown:
                    type_text, name = recovered_unknown
                    records.append(
                        {
                            "kind": "field",
                            "owner": current_raw,
                            "type": type_text,
                            "name": name,
                            "offset": offset,
                            "size": size,
                            "path": path,
                            "line": line_no,
                        }
                    )
                    continue

                if "UnknownData" in decl or "MISSED OFFSET" in line:
                    continue

                # Handles normal fields and bitfields: "unsigned char bFlag : 1"
                left = decl.split(":", 1)[0].strip()
                parts = left.rsplit(None, 1)
                if len(parts) != 2:
                    continue

                type_text, name = parts
                name = name.replace("*", "").replace("&", "").strip()
                type_text = clean_type(type_text)
                if ":" in decl:
                    type_text = "bool" if name.startswith("b") else type_text

                records.append(
                    {
                        "kind": "field",
                        "owner": current_raw,
                        "type": type_text,
                        "name": name,
                        "offset": offset,
                        "size": size,
                        "path": path,
                        "line": line_no,
                    }
                )
                continue

            function_match = FUNCTION_RE.match(line)
            if function_match and "static UClass*" not in line and "//" not in line and "=" not in line:
                decl = clean_type(function_match.group("decl"))
                records.append(
                    {
                        "kind": "function",
                        "owner": current_raw,
                        "decl": decl,
                        "path": path,
                        "line": line_no,
                    }
                )

    return parents, records


def class_path(raw, parents):
    names = []
    seen = set()
    cursor = raw
    while cursor and cursor not in seen:
        seen.add(cursor)
        names.append(clean_ue_name(cursor))
        cursor = parents.get(cursor)
    return ".".join(names)


def leaf_class(class_path_text):
    return class_path_text.split(".", 1)[0].strip()


def parse_template_classes(path):
    classes = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        class_match = CLASS_RE.match(line)
        if not class_match:
            continue
        name = leaf_class(class_match.group("class_path"))
        if name and name not in seen:
            seen.add(name)
            classes.append(name)
    return classes


def symbol_name(class_name, name):
    raw = f"{class_name}_{name}"
    raw = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if raw and raw[0].isdigit():
        raw = "_" + raw
    return raw


def external_offset_items(parents, records):
    items = []
    seen = set()

    for item in records:
        if item["kind"] != "field":
            continue

        owner = clean_ue_name(item["owner"])
        symbol = symbol_name(owner, item["name"])
        if symbol in seen:
            symbol = f'{symbol}_line_{item["line"]}'
        seen.add(symbol)

        items.append(
            {
                "class_path": class_path(item["owner"], parents),
                "class": owner,
                "name": item["name"],
                "symbol": symbol,
                "offset": item["offset"],
                "offset_hex": f'0x{item["offset"]:x}',
                "size": item["size"],
                "type": item["type"],
                "source": str(item["path"]),
                "line": item["line"],
            }
        )

    return items


def write_external_offsets(parents, records, hpp_output, json_output):
    items = external_offset_items(parents, records)
    lines = [
        "#pragma once",
        "#include <cstdint>",
        "",
        "namespace ExternalOffsets {",
    ]

    for item in items:
        lines.append(
            f'    constexpr std::uintptr_t {item["symbol"]} = {item["offset_hex"]}; '
            f'// {item["class_path"]}::{item["name"]}, size {item["size"]}'
        )

    lines.append("}")
    lines.append("")

    hpp_output.write_text("\n".join(lines), encoding="utf-8")
    json_output.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return len(items)


def write_sdk_txt(parents, records, output, style="compact", allowed_classes=None):
    by_owner = {}
    order = []
    allowed = set(allowed_classes) if allowed_classes else None

    for item in records:
        if item["kind"] == "type":
            raw = item["raw"]
            if allowed is not None and clean_ue_name(raw) not in allowed:
                continue
            if raw not in by_owner:
                by_owner[raw] = []
                order.append(raw)
            continue
        owner = item["owner"]
        if allowed is not None and clean_ue_name(owner) not in allowed:
            continue
        if owner not in by_owner:
            by_owner[owner] = []
            order.append(owner)
        by_owner[owner].append(item)

    if allowed_classes:
        class_rank = {name: index for index, name in enumerate(allowed_classes)}
        order.sort(key=lambda raw: (class_rank.get(clean_ue_name(raw), len(class_rank)), clean_ue_name(raw)))

    lines = []
    if style == "dump":
        lines.append("=========== SDK DUMP FROM INTERNAL SDK ===========")
        lines.append("")

    for raw in order:
        lines.append(f"Class: {class_path(raw, parents)}")
        for item in by_owner[raw]:
            if item["kind"] == "field":
                if style == "dump":
                    field_type = clean_dump_type(item["type"])
                    lines.append(f'\t{field_type} {item["name"]}; //[Offset: 0x{item["offset"]:X}, Size: 0x{item["size"]:X}]')
                else:
                    lines.append(f'\t{item["type"]} {item["name"]};//[Offset: 0x{item["offset"]:x}, Size: {item["size"]}]')
            elif item["kind"] == "function":
                if style == "dump":
                    lines.append(f'\t{clean_dump_type(item["decl"])}; //[0x0]')
                else:
                    lines.append(f'\t{item["decl"]};//')
        lines.append("")
        lines.append("--------------------------------")

    output.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_separate_internal_dumps(parents, records, sdku_output, sdkw_output, sdkw_template):
    write_sdk_txt(parents, records, sdku_output, "dump")

    allowed_classes = None
    if sdkw_template and sdkw_template.exists():
        allowed_classes = parse_template_classes(sdkw_template)

    write_sdk_txt(parents, records, sdkw_output, "dump", allowed_classes)
    return len(allowed_classes) if allowed_classes is not None else None


def print_menu():
    print("")
    print("Internal SDK TXT Extractor")
    print("1. Generate SDKU_from_internal.txt and SDKW_from_internal.txt")
    print("2. Generate SDK_from_internal.txt")
    print("3. Generate SDK_from_internal_dump.txt")
    print("4. Generate ExternalOffsets.hpp and ExternalOffsets.json")
    print("0. Exit")
    print("")


def run_interactive_menu(sdk_dir):
    files = sorted(sdk_dir.glob("*_classes.hpp")) + sorted(sdk_dir.glob("*_structs.hpp"))
    parents, records = parse_files(files)

    while True:
        print_menu()
        choice = input("Select option: ").strip()

        if choice == "0":
            print("Exit")
            return

        if choice == "1":
            sdkw_count = write_separate_internal_dumps(
                parents,
                records,
                Path("SDKU_from_internal.txt"),
                Path("SDKW_from_internal.txt"),
                Path("SDKW.txt"),
            )
            print("Wrote SDKU_from_internal.txt")
            print("Wrote SDKW_from_internal.txt")
            if sdkw_count is not None:
                print(f"SDKW output filtered with {sdkw_count} classes from SDKW.txt")
        elif choice == "2":
            write_sdk_txt(parents, records, Path("SDK_from_internal.txt"), "compact")
            print("Wrote SDK_from_internal.txt")
        elif choice == "3":
            write_sdk_txt(parents, records, Path("SDK_from_internal_dump.txt"), "dump")
            print("Wrote SDK_from_internal_dump.txt")
        elif choice == "4":
            count = write_external_offsets(
                parents,
                records,
                Path("ExternalOffsets.hpp"),
                Path("ExternalOffsets.json"),
            )
            print("Wrote ExternalOffsets.hpp")
            print("Wrote ExternalOffsets.json")
            print(f"External offsets: extracted {count}")
        else:
            print("Invalid option")
            continue

        type_count = sum(1 for item in records if item["kind"] == "type")
        field_count = sum(1 for item in records if item["kind"] == "field")
        function_count = sum(1 for item in records if item["kind"] == "function")
        print(f"Read {len(files)} header files")
        print(f"Types: {type_count}, fields: {field_count}, functions: {function_count}")


def main():
    parser = argparse.ArgumentParser(description="Convert UE internal SDK headers to SDK.txt style output.")
    parser.add_argument("sdk_dir", nargs="?", default="SDK", help="Folder containing *_classes.hpp and *_structs.hpp files")
    parser.add_argument("--menu", action="store_true", help="Show an interactive menu instead of typing full commands.")
    parser.add_argument("-o", "--output", default="SDK_from_internal.txt", help="Output SDK.txt-style file")
    parser.add_argument(
        "--style",
        choices=("compact", "dump"),
        default="compact",
        help="Output compact SDK.txt style or SDKU/SDKW-like dump style.",
    )
    parser.add_argument(
        "--separate-dumps",
        action="store_true",
        help="Write separate SDKU-like and SDKW-like dump files from the internal SDK.",
    )
    parser.add_argument("--sdku-output", default="SDKU_from_internal.txt", help="SDKU-like output used with --separate-dumps.")
    parser.add_argument("--sdkw-output", default="SDKW_from_internal.txt", help="SDKW-like output used with --separate-dumps.")
    parser.add_argument(
        "--sdkw-template",
        default="SDKW.txt",
        help="Existing SDKW.txt used to choose classes for the SDKW-like internal output.",
    )
    parser.add_argument(
        "--external-offsets",
        action="store_true",
        help="Generate ExternalOffsets.hpp and ExternalOffsets.json directly from the internal SDK.",
    )
    parser.add_argument("--external-hpp", default="ExternalOffsets.hpp", help="Output C++ header for --external-offsets.")
    parser.add_argument("--external-json", default="ExternalOffsets.json", help="Output JSON file for --external-offsets.")
    args = parser.parse_args()

    sdk_dir = Path(args.sdk_dir)
    if args.menu:
        run_interactive_menu(sdk_dir)
        return

    files = sorted(sdk_dir.glob("*_classes.hpp")) + sorted(sdk_dir.glob("*_structs.hpp"))
    parents, records = parse_files(files)

    if args.external_offsets:
        count = write_external_offsets(parents, records, Path(args.external_hpp), Path(args.external_json))
        print(f"Wrote {args.external_hpp}")
        print(f"Wrote {args.external_json}")
        print(f"External offsets: extracted {count}")
    elif args.separate_dumps:
        sdkw_template = Path(args.sdkw_template) if args.sdkw_template else None
        sdkw_class_count = write_separate_internal_dumps(
            parents,
            records,
            Path(args.sdku_output),
            Path(args.sdkw_output),
            sdkw_template,
        )
        print(f"Wrote {args.sdku_output}")
        print(f"Wrote {args.sdkw_output}")
        if sdkw_class_count is None:
            print("SDKW template not found; SDKW output includes all internal SDK classes")
        else:
            print(f"SDKW output filtered with {sdkw_class_count} classes from {args.sdkw_template}")
    else:
        write_sdk_txt(parents, records, Path(args.output), args.style)
        print(f"Wrote {args.output}")

    type_count = sum(1 for item in records if item["kind"] == "type")
    field_count = sum(1 for item in records if item["kind"] == "field")
    function_count = sum(1 for item in records if item["kind"] == "function")
    print(f"Read {len(files)} header files")
    print(f"Types: {type_count}, fields: {field_count}, functions: {function_count}")


if __name__ == "__main__":
    main()
