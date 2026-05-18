--------------------------- MODULE MatchingEngine ----------------------------
EXTENDS Naturals, Sequences, FiniteSets, TLC

(***************************************************************************
TLC command:
java -jar tla2tools.jar -config tla/ModelMatching.cfg tla/MatchingEngine.tla

Expected state-space size (with default cfg): ~400k-900k states.

Hardest invariant:
NoOrderLoss is hardest because it couples order lifecycle across two structures
(book + trade log) and requires relating residual quantity to cumulative fills.
***************************************************************************)

CONSTANTS MaxOrders, PriceRange

OrderIds == 1..MaxOrders
Qtys == 1..3
Sides == {"B", "S"}

OrderUniverse ==
    { [id |-> id, side |-> s, price |-> p, qty |-> q] :
        id \in OrderIds, s \in Sides, p \in PriceRange, q \in Qtys }

VARIABLES bids, asks, trades, submitted

SeqToSet(s) == {s[i] : i \in 1..Len(s)}

Init ==
    /\ bids = <<>>
    /\ asks = <<>>
    /\ trades = <<>>
    /\ submitted = <<>>

CanSubmit(o) ==
    /\ o \in OrderUniverse
    /\ ~\E x \in submitted : x.id = o.id

InsertBid(o) ==
    LET pos == IF Len(bids) = 0 THEN 1 ELSE
               1 + Cardinality({i \in 1..Len(bids) :
                 bids[i].price > o.price \/ (bids[i].price = o.price /\ bids[i].id < o.id)})
    IN SubSeq(bids, 1, pos - 1) \o <<o>> \o SubSeq(bids, pos, Len(bids))

InsertAsk(o) ==
    LET pos == IF Len(asks) = 0 THEN 1 ELSE
               1 + Cardinality({i \in 1..Len(asks) :
                 asks[i].price < o.price \/ (asks[i].price = o.price /\ asks[i].id < o.id)})
    IN SubSeq(asks, 1, pos - 1) \o <<o>> \o SubSeq(asks, pos, Len(asks))

SubmitBid(o) ==
    /\ o.side = "B"
    /\ CanSubmit(o)
    /\ bids' = InsertBid(o)
    /\ asks' = asks
    /\ trades' = trades
    /\ submitted' = Append(submitted, o)

SubmitAsk(o) ==
    /\ o.side = "S"
    /\ CanSubmit(o)
    /\ asks' = InsertAsk(o)
    /\ bids' = bids
    /\ trades' = trades
    /\ submitted' = Append(submitted, o)

CanMatch == Len(bids) > 0 /\ Len(asks) > 0 /\ bids[1].price >= asks[1].price

Match ==
    /\ CanMatch
    /\ LET b == bids[1] IN
       LET a == asks[1] IN
       LET fillQty == IF b.qty < a.qty THEN b.qty ELSE a.qty IN
       /\ trades' = Append(trades, [buy_id |-> b.id, sell_id |-> a.id, price |-> a.price, qty |-> fillQty])
       /\ bids' = IF b.qty = fillQty
                   THEN SubSeq(bids, 2, Len(bids))
                   ELSE << [b EXCEPT !.qty = b.qty - fillQty] >> \o SubSeq(bids, 2, Len(bids))
       /\ asks' = IF a.qty = fillQty
                   THEN SubSeq(asks, 2, Len(asks))
                   ELSE << [a EXCEPT !.qty = a.qty - fillQty] >> \o SubSeq(asks, 2, Len(asks))
       /\ submitted' = submitted

Next ==
    \/ \E o \in OrderUniverse : SubmitBid(o)
    \/ \E o \in OrderUniverse : SubmitAsk(o)
    \/ Match

BookIds == {o.id : o \in SeqToSet(bids)} \cup {o.id : o \in SeqToSet(asks)}
TradeIds == {t.buy_id : t \in SeqToSet(trades)} \cup {t.sell_id : t \in SeqToSet(trades)}

PriceTimePriority ==
    /\ \A i, j \in 1..Len(bids) : i < j =>
        (bids[i].price > bids[j].price \/ (bids[i].price = bids[j].price /\ bids[i].id < bids[j].id))
    /\ \A i, j \in 1..Len(asks) : i < j =>
        (asks[i].price < asks[j].price \/ (asks[i].price = asks[j].price /\ asks[i].id < asks[j].id))

NoDoubleFill ==
    /\ \A id \in OrderIds :
         Cardinality({t \in SeqToSet(trades) : t.buy_id = id}) <= 1
    /\ \A id \in OrderIds :
         Cardinality({t \in SeqToSet(trades) : t.sell_id = id}) <= 1

NoOrderLoss == \A o \in SeqToSet(submitted) : (o.id \in BookIds) \/ (o.id \in TradeIds)

Spec == Init /\ [][Next]_<<bids, asks, trades, submitted>>

=============================================================================
