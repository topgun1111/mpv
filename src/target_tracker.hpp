#pragma once
#include "track_math.hpp"
#include <algorithm>
#include <cmath>
#include <optional>
#include <vector>

namespace native {
struct Detection { Rect box; double confidence{0}; int category{0}; };
inline double intersectionOverUnion(Rect a, Rect b) {
    if (!valid(a) || !valid(b)) return 0.0;
    const double left=std::max(a.x,b.x), top=std::max(a.y,b.y);
    const double right=std::min(a.x+a.w,b.x+b.w), bottom=std::min(a.y+a.h,b.y+b.h);
    const double overlap=std::max(0.0,right-left)*std::max(0.0,bottom-top);
    const double area=a.w*a.h+b.w*b.h-overlap;
    return area>0?overlap/area:0.0;
}
class TargetTracker {
public:
    void reset() { target_.reset(); lost_=0; }
    void select(Rect rect) { if (!valid(rect)) {reset(); return;} target_=rect; lost_=0; }
    std::optional<Rect> update(const std::vector<Detection>& detections) {
        if (!target_) return std::nullopt;
        const Detection* best=nullptr;
        double bestScore=-1.0;
        for (const auto& detection: detections) {
            if (!valid(detection.box) || !std::isfinite(detection.confidence) || detection.confidence<0.25) continue;
            const double overlap=intersectionOverUnion(*target_,detection.box);
            const double dx=(target_->x+target_->w*0.5)-(detection.box.x+detection.box.w*0.5);
            const double dy=(target_->y+target_->h*0.5)-(detection.box.y+detection.box.h*0.5);
            const double proximity=std::max(0.0,1.0-std::hypot(dx,dy)*2.0);
            const double score=0.8*overlap+0.2*proximity;
            if (score>bestScore) { bestScore=score; best=&detection; }
        }
        if (best && bestScore>=0.22) { target_=best->box; lost_=0; return target_; }
        ++lost_;
        if (lost_>90) reset();
        return std::nullopt;
    }
    bool selected() const { return target_.has_value(); }
    int missingFrames() const { return lost_; }
private:
    std::optional<Rect> target_;
    int lost_{0};
};
}
