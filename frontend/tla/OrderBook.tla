----------------------------- MODULE OrderBook -------------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

(***************************************************************************
TLC command:
java -jar tla2tools.jar -config tla/ModelOrderBook.cfg tla/OrderBook.tla

Expected state-space size (with default cfg): ~500k-1.2M states.

Hardest invariant:
QuantityConservation is hardest because every transition must preserve a global
accounting identity across three evolving sets: live book, submitted, and fills.
***************************************************************************)

CONSTANTS PriceRange, OrderIds, Qtys

OrderUniverse ==
    { [id |-> id, price |-> p, qty |-> q] : id \in OrderIds, p \in PriceRange, q \in Qtys }

VARIABLES book, submitted, cancelled, fills

SeqToSet(s) == {s[i] : i \in 1..Len(s)}

SeqQtySum(s) ==
    IF Len(s) = 0 THEN 0 ELSE s[1].qty + SeqQtySum(SubSeq(s, 2, Len(s)))

BookQtyAt(p) == SeqQtySum(book[p])

Init ==
    /\ book = [p \in PriceRange |-> <<>>]
    /\ submitted = <<>>
    /\ cancelled = {}
    /\ fills = <<>>

CanAdd(o) == o \in OrderUniverse /\ ~\E x \in submitted : x.id = o.id

Add(o) ==
    /\ CanAdd(o)
    /\ book' = [book EXCEPT ![o.price] = Append(@, o)]
    /\ submitted' = Append(submitted, o)
    /\ cancelled' = cancelled
    /\ fills' = fills

Cancel(order_id) ==
    /\ order_id \in {o.id : o \in SeqToSet(submitted)}
    /\ LET priceHit == {p \in PriceRange : \E x \in SeqToSet(book[p]) : x.id = order_id} IN
       /\ priceHit # {}
       /\ LET p == CHOOSE px \in priceHit : TRUE IN
          /\ book' = [book EXCEPT ![p] = SelectSeq(@, LAMBDA x: x.id # order_id)]
          /\ submitted' = submitted
          /\ cancelled' = cancelled \cup {order_id}
          /\ fills' = fills

CanFill(p, q) ==
    /\ p \in PriceRange
    /\ q \in Qtys
    /\ Len(book[p]) > 0
    /\ book[p][1].qty >= q
    /\ book[p][1].id \notin cancelled

Fill(p, q) ==
    /\ CanFill(p, q)
    /\ LET top == book[p][1] IN
       LET rem == top.qty - q IN
       /\ fills' = Append(fills, [id |-> top.id, price |-> p, qty |-> q])
       /\ book' = IF rem = 0
                  THEN [book EXCEPT ![p] = SubSeq(@, 2, Len(@))]
                  ELSE [book EXCEPT ![p] = << [top EXCEPT !.qty = rem] >> \o SubSeq(@, 2, Len(@))]
       /\ submitted' = submitted
       /\ cancelled' = cancelled

Next ==
    \/ \E o \in OrderUniverse : Add(o)
    \/ \E id \in OrderIds : Cancel(id)
    \/ \E p \in PriceRange, q \in Qtys : Fill(p, q)

BestBid == IF {p \in PriceRange : Len(book[p]) > 0} = {} THEN -1 ELSE Max({p \in PriceRange : Len(book[p]) > 0})
BestAsk == IF {p \in PriceRange : Len(book[p]) > 0} = {} THEN -1 ELSE Min({p \in PriceRange : Len(book[p]) > 0})

NoGhostOrders == \A f \in SeqToSet(fills) : f.id \notin cancelled

SubmittedQty == SeqQtySum(submitted)
FilledQty == SeqQtySum(fills)
BookQty == Sum({BookQtyAt(p) : p \in PriceRange})

QuantityConservation == BookQty + FilledQty <= SubmittedQty

BestBidBelowBestAsk ==
    IF BestBid = -1 \/ BestAsk = -1 THEN TRUE ELSE BestBid < BestAsk

Spec == Init /\ [][Next]_<<book, submitted, cancelled, fills>>

=============================================================================
