------------------------------ MODULE OrderBook ------------------------------
EXTENDS Naturals, Sequences, TLC

VARIABLES bids, asks, mid_price

BestBid == IF Len(bids) = 0 THEN 0 ELSE Max({bids[i] : i \in 1..Len(bids)})
BestAsk == IF Len(asks) = 0 THEN 0 ELSE Min({asks[i] : i \in 1..Len(asks)})

Init ==
  /\ bids = <<100>>
  /\ asks = <<101>>
  /\ mid_price = (BestBid + BestAsk) / 2

AddBid(p) ==
  /\ p < BestAsk
  /\ bids' = Append(bids, p)
  /\ asks' = asks
  /\ mid_price' = (IF Len(bids') > 0 /\ Len(asks') > 0 THEN (BestBid + BestAsk) / 2 ELSE mid_price)

AddAsk(p) ==
  /\ p > BestBid
  /\ asks' = Append(asks, p)
  /\ bids' = bids
  /\ mid_price' = (IF Len(bids') > 0 /\ Len(asks') > 0 THEN (BestBid + BestAsk) / 2 ELSE mid_price)

RemoveBid ==
  /\ Len(bids) > 0
  /\ bids' = Tail(bids)
  /\ asks' = asks
  /\ mid_price' = (IF Len(bids') > 0 /\ Len(asks') > 0 THEN (BestBid + BestAsk) / 2 ELSE mid_price)

RemoveAsk ==
  /\ Len(asks) > 0
  /\ asks' = Tail(asks)
  /\ bids' = bids
  /\ mid_price' = (IF Len(bids') > 0 /\ Len(asks') > 0 THEN (BestBid + BestAsk) / 2 ELSE mid_price)

Next ==
  \/ \E p \in 1..100000 : AddBid(p)
  \/ \E p \in 1..100000 : AddAsk(p)
  \/ RemoveBid
  \/ RemoveAsk

MidInvariant == (Len(bids) > 0 /\ Len(asks) > 0) => mid_price = (BestBid + BestAsk) / 2
NoCrossedBook == (Len(bids) > 0 /\ Len(asks) > 0) => BestBid < BestAsk

Spec == Init /\ [][Next]_<<bids, asks, mid_price>>

THEOREM Spec => []NoCrossedBook
=============================================================================
