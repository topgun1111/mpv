#pragma once
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace native {
struct Rect { double x{}, y{}, w{}, h{}; };
struct View { double cx{0.5}, cy{0.5}, zoom{1.0}; };
inline double clamp01(double x) { return std::clamp(x, 0.0, 1.0); }
inline bool valid(Rect r) { return std::isfinite(r.x)&&std::isfinite(r.y)&&std::isfinite(r.w)&&std::isfinite(r.h)&&r.w>0&&r.h>0; }
class Camera {
public:
    void reset() { initialized_=false; state_={}; }
    View update(Rect target, double frameAspect, double outputAspect, double dt, double occupancy=0.65) {
        if (!valid(target) || !(frameAspect>0) || !(outputAspect>0) || !(dt>=0) || !std::isfinite(dt) || !(occupancy>0 && occupancy<=1)) throw std::invalid_argument("invalid camera input");
        // Coordinates are normalized to the source image. Preserve output aspect ratio.
        const double visibleWidthAt1=std::min(1.0, outputAspect/frameAspect);
        const double visibleHeightAt1=std::min(1.0, frameAspect/outputAspect);
        const double desiredZoom=std::clamp(std::max(target.w/(visibleWidthAt1*occupancy), target.h/(visibleHeightAt1*occupancy)), 0.01, 1.0);
        View desired{clamp01(target.x+target.w/2),clamp01(target.y+target.h/2),1.0/desiredZoom};
        desired.zoom=std::clamp(desired.zoom,1.0,8.0);
        if (!initialized_) { state_=desired; initialized_=true; }
        else {
            const double alpha=1-std::exp(-std::min(dt,1.0)*4.0);
            state_.cx+=alpha*(desired.cx-state_.cx);
            state_.cy+=alpha*(desired.cy-state_.cy);
            state_.zoom+=alpha*(desired.zoom-state_.zoom);
        }
        const double halfW=visibleWidthAt1/(2*state_.zoom);
        const double halfH=visibleHeightAt1/(2*state_.zoom);
        state_.cx=std::clamp(state_.cx,halfW,1-halfW);
        state_.cy=std::clamp(state_.cy,halfH,1-halfH);
        return state_;
    }
private:
    View state_{}; bool initialized_{false};
};
}
