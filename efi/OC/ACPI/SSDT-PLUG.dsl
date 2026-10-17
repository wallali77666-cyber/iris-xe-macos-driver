/*
 * SSDT-PLUG — declares plugin-type=1 on the first processor object so macOS
 * loads X86PlatformPlugin (CPU power management) on this laptop.
 *
 * Reference machine: Dell Latitude 5420 (Tiger Lake). The CPU objects in Dell
 * TGL ACPI live under \_SB.PR00. After the first boot, check the SysReport
 * ACPI dump (written to the USB ESP by OpenCore) and fix the name here if it
 * differs — e.g. \_SB.CPU0 on other firmware.
 *
 * Compiled to SSDT-PLUG.aml by tools/efi/assemble.sh (iasl).
 */
DefinitionBlock ("", "SSDT", 2, "IXOC", "PLUG", 0x00000000)
{
    External (_SB_.PR00, ProcessorObj)

    Scope (\_SB.PR00)
    {
        Method (_DSM, 4, NotSerialized)
        {
            If ((Arg2 == Zero))
            {
                Return (Buffer (One) { 0x03 })
            }
            Return (Package (0x02)
            {
                "plugin-type",
                One
            })
        }
    }
}
