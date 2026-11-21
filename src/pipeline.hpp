#pragma once
#include "track_math.hpp"
#include "target_tracker.hpp"
#include <opencv2/opencv.hpp>
#include <opencv2/dnn.hpp>
#include <functional>
#include <optional>
#include <string>
#include <vector>

namespace native {
struct Person { Rect box; float score{}; std::vector<cv::Point2f> joints; };
struct Settings { double occupancy=.70; int outputWidth=1280, outputHeight=720; double confidence=.35; bool drawSkeleton=true; };
struct FrameResult { cv::Mat image; std::vector<Person> people; int tracked=-1; bool targetLost=false; };
class Pipeline {
public:
 explicit Pipeline(Settings s={});
 bool loadModel(const std::string& path, std::string& error);
 void reset();
 void select(double x, double y);
 FrameResult process(const cv::Mat& frame, double dt);
 bool hasModel() const { return modelReady_; }
 const std::string& backend() const { return backend_; }
private:
 Settings settings_; cv::dnn::Net net_; bool modelReady_=false; std::string backend_="OpenCV HOG CPU";
 cv::HOGDescriptor hog_; Camera camera_; TargetTracker tracker_;
 std::optional<cv::Point2d> pendingSelect_; std::optional<Rect> lastBox_; View lastView_{}; double sourceAspect_=16.0/9.0;
 std::vector<Person> detect(const cv::Mat& image);
 static cv::Rect cropRect(View view, cv::Size source, cv::Size output);
};
}
