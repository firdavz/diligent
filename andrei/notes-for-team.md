# Notes for the team

## For Clotilde (and her Claude): thank you (21 Nov, 14:30)

Thank you from Andrei and his Claude. Your explainers turned the scores around this afternoon: own-account transfers
with the 5× rule, returning customers, documented events, refunds, the payments and FX invoice / contract / schedule /
payment-file matching, gift letters, invoice-finance advances and group collections. On our 326 SOP-reasoned labels the
system went from closing 3 of 29 closable bank cases to **95% accuracy at the bank, 96% at e-money and 91% at
investment, with zero wrongful closes**. The invoice-reuse fix was a great catch too.

If you have time before the 15:30 freeze, the remaining gap is **payments and FX** (70% accurate, 57% cost saved):
- own-account and returning-customer closes sent to RFI: PX-CS986980, PX-CS985367, PX-CS983791, PX-CS992649;
- the purchase-order shape (PX-CS986423), which waits on Ahmad's answer about own-name funding accounts (D20);
- freight forwarders with no documents escalated instead of RFI: PX-CS983382.

`python3 eval/score.py payments_fx` lists them with the labeller's note.
