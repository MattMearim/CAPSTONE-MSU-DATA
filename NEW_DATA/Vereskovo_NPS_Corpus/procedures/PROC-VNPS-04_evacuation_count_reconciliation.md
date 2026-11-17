# Evacuation and population count reconciliation - VNPS-1

FICTIONAL TRAINING PROCEDURE - written for testing the FRIB decision-support system with the fictional Vereskovo NPS records. Not a real or FRIB operating procedure.

Version: VNPS-1 (2026-11-17)

## Purpose
Reconcile population and evacuation numbers that do not match across records.

## Steps
1. Separate the quantities: residents on 1 Jan 1986 [DOC-1986-0003 - Vereskovsk town executive committee: population on 1 January 1986](../corpus/DOC-1986-0003_town-passport-1986.md); planning figure [DOC-1985-0002 - Civil defense plan of Vereskovsk: evacuation section (extract)](../corpus/DOC-1985-0002_cd-plan-1985.md); persons evacuated by bus [DOC-1986-0041 - Report of the chief of staff of regional civil defense on the evacuation of Vereskovsk](../corpus/DOC-1986-0041_karpenko-report.md) and [DOC-1986-0046 - Evacuation of Vereskovsk: bus column dispatch record, 18 May 1986](../corpus/DOC-1986-0046_evac-buses-0518.csv).
2. Use the settlement table [DOC-1986-0089 - Evacuated population by settlement, as of 1 July 1986](../corpus/DOC-1986-0089_evac-by-settlement.csv) for totals; compare with the official total of 10 June [DOC-1986-0073 - Report of the evacuation commission: evacuated population as of 10 June 1986](../corpus/DOC-1986-0073_evac-total-report.md).
3. Check the date of each figure: settlements evacuated after a report are not in its total (zone decisions: [DOC-1987-0028 - Zone assignment decisions, 1986-1987](../corpus/DOC-1987-0028_zone-changes.csv)).
4. Report which figure answers the question asked (residents, evacuated, planned) and its source.
