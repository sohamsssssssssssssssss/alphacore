#ifndef DETECTION_H
#define DETECTION_H

typedef struct {
    int level_idx;
    double confidence;
    int detected;
} IcebergResult;

IcebergResult iceberg_scan(double* prices, double* qtys, int count, double threshold);
double spoof_scan(double* cur_prices, double* cur_qtys, double* prev_prices, double* prev_qtys,
                  int count, double mid_price, double distance_threshold_bps, double qty_threshold);

#endif
