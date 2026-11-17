# Liquidator dose record check - VNPS-1

FICTIONAL TRAINING PROCEDURE - written for testing the FRIB decision-support system with the fictional Vereskovo NPS records. Not a real or FRIB operating procedure.

Version: VNPS-1 (2026-11-17)

## Purpose
Check worker dose records across the 1986 and 1987 record systems.

## Steps
1. Apply the limit in force on the date of work: 25 rem (1986) [DOC-1986-0058 - Ministry of Health order: dose limit for persons participating in the elimination of the consequences of the accident (1986)](../corpus/DOC-1986-0058_dose-limit-1986.md); 10 rem/year from 1 Jan 1987 [DOC-1986-0118 - Ministry of Health order: dose limit for 1987](../corpus/DOC-1986-0118_dose-limit-1987.md); station transition [DOC-1987-0001 - Station order No. 38 on dose limits for 1987](../corpus/DOC-1987-0001_station-dose-order.md).
2. Map 1986 card numbers (L86-######) to the 1987 registry (VR87-RR-NNNNN): [DOC-1987-0005 - Ministry of Health order on the all-union registry of persons exposed as a result of the accident](../corpus/DOC-1987-0005_registry-order.md) and [DOC-1987-0011 - All-union liquidator registry: extract for V-NPS contingents (1987 format)](../corpus/DOC-1987-0011_registry-1987.csv).
3. Flag doses recorded exactly at the limit (25.0) and records without a 1986 card: [DOC-1987-0012 - Registry office: report on the conversion of 1986 cards into the all-union registry](../corpus/DOC-1987-0012_registry-migration.md).
4. Doses in roentgen (R) and rem are treated as approximately equal for gamma; see [PROC-VNPS-05](PROC-VNPS-05_radiation_units_reference.md).
5. Cross-check roof work against [DOC-1986-0109 - Roof clearing (Unit 3 roof, zone 'M'): exposure list, 20-25 Sept 1986](../corpus/DOC-1986-0109_liquidator-roof-sep86.csv) and [DOC-1986-0110 - Report on the completion of clearing of the Unit 3 roof](../corpus/DOC-1986-0110_roof-completion.md).
