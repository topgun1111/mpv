#include "track_math.hpp"
#include <cassert>
#include <cmath>
#include <stdexcept>
int main() {
    using namespace native;
    Camera c;
    auto v=c.update({0.4,0.4,0.2,0.2},16.0/9,16.0/9,0.033);
    assert(std::abs(v.cx-0.5)<1e-9);
    assert(v.zoom>1 && v.zoom<=8);
    auto v2=c.update({0.6,0.4,0.2,0.2},16.0/9,16.0/9,0.033);
    assert(v2.cx>v.cx && v2.cx<0.7);
    bool threw=false;
    try { c.update({0,0,0,0},1,1,0.1); } catch(const std::invalid_argument&) {threw=true;}
    assert(threw);
    c.reset();
    auto v3=c.update({0,0,0.01,0.01},1,1,0);
    assert(v3.cx>=1/(2*v3.zoom)-1e-9);
}
