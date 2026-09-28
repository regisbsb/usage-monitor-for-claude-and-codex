# pyright: reportUndefinedVariable=false

VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=(1, 0, 2, 0),
        prodvers=(1, 0, 2, 0),
        mask=0x3F,
        flags=0x0,
        OS=0x40004,          # VOS_NT_WINDOWS32
        fileType=0x1,        # VFT_APP
        subtype=0x0,
    ),
    kids=[
        StringFileInfo([
            StringTable(
                '040904B0',  # Lang: US English, Charset: Unicode
                [
                    StringStruct('CompanyName', 'Usage Monitor contributors'),
                    StringStruct('FileDescription', 'Usage Monitor for Claude and Codex'),
                    StringStruct('FileVersion', '1.0.2.0'),
                    StringStruct('InternalName', 'UsageMonitorForClaudeAndCodex'),
                    StringStruct('OriginalFilename', 'UsageMonitorForClaudeAndCodex.exe'),
                    StringStruct('ProductName', 'Usage Monitor for Claude and Codex'),
                    StringStruct('ProductVersion', '1.0.2.0'),
                ],
            ),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)
