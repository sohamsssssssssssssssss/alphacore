#include "detection.h"
#include <math.h>

IcebergResult iceberg_scan(double* prices, double* qtys, int count, double threshold) {
    int i;
    double total = 0.0;
    IcebergResult out;
    (void)prices;

    out.level_idx = -1;
    out.confidence = 0.0;
    out.detected = 0;

    for (i = 0; i < count; i++) total += qtys[i];
    if (total <= 0.0) return out;

    for (i = 0; i < count; i++) {
        double ratio = qtys[i] / total;
        if (ratio > threshold) {
            out.level_idx = i;
            out.confidence = ratio;
            out.detected = 1;
            return out;
        }
    }
    return out;
}

double spoof_scan(double* cur_prices, double* cur_qtys, double* prev_prices, double* prev_qtys,
                  int count, double mid_price, double distance_threshold_bps, double qty_threshold) {
    int i;
    double score = 0.0;
    if (mid_price <= 0.0) return 0.0;

    for (i = 0; i < count; i++) {
        double prev_q = prev_qtys[i];
        double cur_q = cur_qtys[i];
        double p = prev_prices[i];
        double dist_bps = fabs(p - mid_price) / mid_price * 10000.0;
        (void)cur_prices;
        if (prev_q > qty_threshold && cur_q <= 0.0 && dist_bps > distance_threshold_bps) {
            score += 0.25;
        }
    }
    if (score > 1.0) score = 1.0;
    if (score < 0.0) score = 0.0;
    return score;
}
