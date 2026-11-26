# Prototype pod dump (11.2.1 15D40260u NonUI, B238aAP): what is in it (2026-11-24)

Looked at the author's extract in <local_protopod_extract>. 

- diag-B238.im4p / diag-B238A.im4p (type `diag`), console (`pert`), hammer (`hmmr`), rbm (`rbmt`),
  sepboot (`rsep`): bare IM4P payloads. No ticket, no signature, no key bag (not encrypted).
  They can only be started through the Boot ROM route we already use (tethered).
- devicetree.img4 and sep-firmware.img4: full IMG4 with the prototype's own ticket.
  Ticket properties: CHIP 0x7000, BORD 0x38, CPRO true, CSEC true (production fused), SDOM 1, CEPO 1,
  ECID present, BNCH present. No allow-mix-and-match property.
  Objects listed include diag, hmmr, pert, rbmt, rsep, rfta/rfts/ftap/ftsp next to the usual ones,
  so Apple's internal signing server signs diags and factory tests per unit.
- Result: nothing here starts by itself on another pod. Every signed thing is tied to that one unit,
  everything else is unsigned.
