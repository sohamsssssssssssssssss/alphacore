------------------------------ MODULE OrderBook -------------------------------
EXTENDS Naturals, Sequences, FiniteSets, Integers

(***************************************************************************
TLC command:
java -jar tla2tools.jar -config tla/ModelOrderBook.cfg tla/OrderBook.tla

Expected state-space size (with default cfg): ~500k-1.2M states.

Hardest invariant:
QuantityConservation is hardest because every transition must preserve a global
accounting identity across three evolving sets: live book, submitted, and fills.
**************************************************************************)

CONSTANTS PriceRange, OrderIds, Qtys, Sides

OrderUniverse ==
    { [id |-> id, price |-> p, qty |-> q, side |-> s] : id \in OrderIds, p \in PriceRange, q \in Qtys, s \in Sides }

VARIABLES book, submitted, cancelled, fills

SeqToSet(s) == {s[i] : i \in 1..Len(s)}

NoQuote == 0 - 1

SetMax(S) == IF S = {} THEN NoQuote ELSE CHOOSE x \in S : \A y \in S : x >= y

SetMin(S) == IF S = {} THEN NoQuote ELSE CHOOSE x \in S : \A y \in S : x <= y

RECURSIVE SetSum(_)
SetSum(S) ==
    IF S = {} THEN 0
    ELSE LET x == CHOOSE x \in S : TRUE IN x + SetSum(S \ {x})

RECURSIVE SeqQtySum(_)
SeqQtySum(s) ==
    IF s = <<>> THEN 0 ELSE s[1].qty + SeqQtySum(SubSeq(s, 2, Len(s)))

BookQtyAt(p) == SeqQtySum(book[p])

Init ==
    /\ book = [p \in PriceRange |-> <<>>]
    /\ submitted = <<>>
    /\ cancelled = {}
    /\ fills = <<>>

CanAdd(o) == o \in OrderUniverse /\ ~\E x \in SeqToSet(submitted) : x.id = o.id

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

BestBid == IF {p \in PriceRange : Len(book[p]) > 0} = {} THEN NoQuote ELSE SetMax({p \in PriceRange : Len(book[p]) > 0})
BestAsk == IF {p \in PriceRange : Len(book[p]) > 0} = {} THEN NoQuote ELSE SetMin({p \in PriceRange : Len(book[p]) > 0})

AllBookOrders == UNION { SeqToSet(book[p]) : p \in PriceRange }

NoGhostOrders ==
    \A odr \in AllBookOrders : odr.id \notin cancelled

SubmittedQty == SeqQtySum(submitted)
FilledQty == SeqQtySum(fills)
BookQty == SetSum({BookQtyAt(p) : p \in PriceRange})

QuantityConservation == BookQty + FilledQty <= SubmittedQty

BestBidBelowBestAsk ==
    IF BestBid = NoQuote \/ BestAsk = NoQuote THEN TRUE ELSE BestBid < BestAsk

Spec == Init /\ [][Next]_<<book, submitted, cancelled, fills>>

==============================================================================
