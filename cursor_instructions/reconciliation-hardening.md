Add reconciliation invariant guard

Right now you rely on logic correctness.

I would add one defensive assertion:

After reconciliation:

Assert:
    stored_quantity >= 0
    remaining_balance_to_reconcile >= 0


Just in case future code paths mutate state.

Very cheap safety net.