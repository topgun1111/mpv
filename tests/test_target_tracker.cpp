#include "target_tracker.hpp"
#include <cassert>
#include <cmath>
#include <vector>
int main() {
    using namespace native;
    assert(intersectionOverUnion({0,0,0.5,0.5},{0,0,0.5,0.5})==1);
    assert(intersectionOverUnion({0,0,0.1,0.1},{0.9,0.9,0.1,0.1})==0);
    TargetTracker t;
    assert(!t.update({Detection{{0.1,0.1,0.2,0.2},0.9}}));
    t.select({0.1,0.1,0.2,0.2});
    auto hit=t.update({Detection{{0.11,0.11,0.2,0.2},0.9}});
    assert(hit && std::abs(hit->x-0.11)<1e-9);
    assert(!t.update({}));
    assert(t.selected() && t.missingFrames()==1);
    for(int i=0;i<90;i++) t.update({});
    assert(!t.selected());
    t.select({0,0,-1,1});
    assert(!t.selected());
}
