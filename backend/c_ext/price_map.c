#include "price_map.h"

void ob_clear(OrderBook* ob) {
    int i;
    ob->bid_count = 0;
    ob->ask_count = 0;
    for (i = 0; i < MAX_LEVELS; i++) {
        ob->bids[i].price = 0.0;
        ob->bids[i].quantity = 0.0;
        ob->bids[i].active = 0;
        ob->asks[i].price = 0.0;
        ob->asks[i].quantity = 0.0;
        ob->asks[i].active = 0;
    }
}

void ob_insert_bid(OrderBook* ob, double price, double qty) {
    if (ob->bid_count >= MAX_LEVELS) return;
    ob->bids[ob->bid_count].price = price;
    ob->bids[ob->bid_count].quantity = qty;
    ob->bids[ob->bid_count].active = 1;
    ob->bid_count++;
}

void ob_insert_ask(OrderBook* ob, double price, double qty) {
    if (ob->ask_count >= MAX_LEVELS) return;
    ob->asks[ob->ask_count].price = price;
    ob->asks[ob->ask_count].quantity = qty;
    ob->asks[ob->ask_count].active = 1;
    ob->ask_count++;
}

PriceLevel* ob_best_bid(OrderBook* ob) {
    int i;
    int best = -1;
    for (i = 0; i < ob->bid_count; i++) {
        if (!ob->bids[i].active) continue;
        if (best == -1 || ob->bids[i].price > ob->bids[best].price) best = i;
    }
    return (best == -1) ? 0 : &ob->bids[best];
}

PriceLevel* ob_best_ask(OrderBook* ob) {
    int i;
    int best = -1;
    for (i = 0; i < ob->ask_count; i++) {
        if (!ob->asks[i].active) continue;
        if (best == -1 || ob->asks[i].price < ob->asks[best].price) best = i;
    }
    return (best == -1) ? 0 : &ob->asks[best];
}

double ob_mid_price(OrderBook* ob) {
    PriceLevel* b = ob_best_bid(ob);
    PriceLevel* a = ob_best_ask(ob);
    if (!b || !a) return 0.0;
    return (b->price + a->price) / 2.0;
}

double ob_spread_bps(OrderBook* ob) {
    PriceLevel* b = ob_best_bid(ob);
    PriceLevel* a = ob_best_ask(ob);
    double mid;
    if (!b || !a) return 0.0;
    mid = (b->price + a->price) / 2.0;
    if (mid <= 0.0) return 0.0;
    return ((a->price - b->price) / mid) * 10000.0;
}
