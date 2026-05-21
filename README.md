# Internal SDK TXT Extractor

Convert Unreal Engine internal SDK headers into readable SDK dump text files.

This project is set up to generate two separate TXT outputs from the internal `SDK/` folder:

- `SDKU_from_internal.txt` - full internal SDK dump
- `SDKW_from_internal.txt` - SDKW-style internal dump, filtered and ordered using `SDKW.txt`

No C++ header or JSON output is required for the normal workflow.

## Files

- `internal_sdk_to_sdktxt.py` - main converter for internal SDK headers
- `SDK/` - internal SDK header folder used as input
- `SDKU.txt` - reference SDKU dump
- `SDKW.txt` - reference SDKW dump and template for SDKW class filtering
- `SDKU_from_internal.txt` - generated SDKU-style TXT output
- `SDKW_from_internal.txt` - generated SDKW-style TXT output

## Requirements

- Python 3
- Internal SDK headers inside the `SDK/` folder

No external Python packages are needed.

## Generate Both TXT Dumps

Run this from the repository folder:

```powershell
python internal_sdk_to_sdktxt.py SDK --separate-dumps --sdku-output SDKU_from_internal.txt --sdkw-output SDKW_from_internal.txt --sdkw-template SDKW.txt
```

The command writes only TXT dump files:

```text
SDKU_from_internal.txt
SDKW_from_internal.txt
```

## Run Without Pasting Commands

Double-click:

```text
run_dump_menu.bat
```

Or run:

```powershell
python internal_sdk_to_sdktxt.py SDK --menu
```

Then choose an option by number:

```text
1. Generate SDKU_from_internal.txt and SDKW_from_internal.txt
2. Generate SDK_from_internal.txt
3. Generate SDK_from_internal_dump.txt
```

## Generate One TXT Dump

Compact SDK.txt-style output:

```powershell
python internal_sdk_to_sdktxt.py SDK -o SDK_from_internal.txt
```

Dump-style TXT output:

```powershell
python internal_sdk_to_sdktxt.py SDK -o SDK_from_internal_dump.txt --style dump
```

## Output Format

Generated dump entries look like this:

```text
Class: World.Object
	Level* PersistentLevel; //[Offset: 0x20, Size: 0x4]
	NetDriver* NetDriver; //[Offset: 0x24, Size: 0x4]

--------------------------------
```

Functions are also included when they are available in the internal SDK headers:

```text
	void ExecuteUbergraph(int EntryPoint); //[0x0]
```

## SDKU vs SDKW

`SDKU_from_internal.txt` includes every class and struct parsed from the internal SDK headers.

`SDKW_from_internal.txt` uses `SDKW.txt` as a template. It only includes classes found in `SDKW.txt`, and keeps that class order where possible.

If `SDKW.txt` is missing, the SDKW output falls back to including all parsed internal SDK classes.

## Notes

- Unknown padding fields like `UnknownData` are skipped.
- Missed offset placeholders are skipped.
- UE prefixes such as `U`, `A`, and `F` are cleaned in class and struct names.
- Common UE container types like `TArray`, `TMap`, `TEnumAsByte`, and `TScriptInterface` are converted into dump-style text.
