#ifndef PRICE_MAP_H
#define PRICE_MAP_H

#define MAX_LEVELS 1024

typedef struct {
    double price;
    double quantity;
    int active;
} PriceLevel;

typedef struct {
    PriceLevel bids[MAX_LEVELS];
    PriceLevel asks[MAX_LEVELS];
    int bid_count;
    int ask_count;
} OrderBook;

void ob_clear(OrderBook* ob);
void ob_insert_bid(OrderBook* ob, double price, double qty);
void ob_insert_ask(OrderBook* ob, double price, double qty);
PriceLevel* ob_best_bid(OrderBook* ob);
PriceLevel* ob_best_ask(OrderBook* ob);
double ob_mid_price(OrderBook* ob);
double ob_spread_bps(OrderBook* ob);

#endif
