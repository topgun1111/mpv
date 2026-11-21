#include "pipeline.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace native {
Pipeline::Pipeline(Settings s):settings_(s) {
 if(s.outputWidth<=0||s.outputHeight<=0||s.occupancy<=0||s.occupancy>1) throw std::invalid_argument("Invalid pipeline settings");
 hog_.setSVMDetector(cv::HOGDescriptor::getDefaultPeopleDetector());
}
bool Pipeline::loadModel(const std::string& path,std::string& error) {
 modelReady_=false; backend_="OpenCV HOG CPU"; net_=cv::dnn::Net();
 if(path.empty()) return true;
 try {
  net_=cv::dnn::readNetFromONNX(path);
  if(net_.empty()) throw std::runtime_error("ONNX network is empty");
  net_.setPreferableBackend(cv::dnn::DNN_BACKEND_OPENCV);
  net_.setPreferableTarget(cv::dnn::DNN_TARGET_CPU);
  modelReady_=true; backend_="ONNX pose / OpenCV DNN CPU"; return true;
 } catch(const std::exception& e) { error=e.what(); net_=cv::dnn::Net(); return false; }
}
void Pipeline::reset() { camera_.reset();tracker_.reset();pendingSelect_.reset();lastBox_.reset();lastView_={}; }
void Pipeline::select(double x,double y) { if(std::isfinite(x)&&std::isfinite(y)&&x>=0&&x<=1&&y>=0&&y<=1) { /* Preview coordinates are relative to the current crop, not the original video. */
  const double sourceAspect=sourceAspect_,outputAspect=double(settings_.outputWidth)/settings_.outputHeight;
  const double fullW=std::min(1.0,outputAspect/sourceAspect);
  const double fullH=std::min(1.0,sourceAspect/outputAspect);
  pendingSelect_=cv::Point2d(lastView_.cx+(x-.5)*fullW/lastView_.zoom,lastView_.cy+(y-.5)*fullH/lastView_.zoom);
 } }
static float sigmoid(float x) {return 1.f/(1.f+std::exp(-x));}
std::vector<Person> Pipeline::detect(const cv::Mat& image) {
 std::vector<Person> persons;
 if(modelReady_) {
  // YOLOv8/YOLO11 pose ONNX: [1, 56, N] or [1, N, 56], 17 keypoints.
  constexpr int side=640;
  const double scale=std::min(side/double(image.cols),side/double(image.rows));
  const int nw=std::max(1,int(std::round(image.cols*scale))),nh=std::max(1,int(std::round(image.rows*scale)));
  cv::Mat resized,letter(side,side,CV_8UC3,cv::Scalar(114,114,114));
  cv::resize(image,resized,cv::Size(nw,nh));
  int ox=(side-nw)/2,oy=(side-nh)/2;resized.copyTo(letter(cv::Rect(ox,oy,nw,nh)));
  cv::Mat blob=cv::dnn::blobFromImage(letter,1.0/255.0,cv::Size(side,side),cv::Scalar(),true,false);
  net_.setInput(blob);cv::Mat out=net_.forward();
  if(out.dims!=3||out.size[0]!=1) throw std::runtime_error("Unsupported ONNX output rank; expected [1,56,N] or [1,N,56]");
  const bool channelsFirst=out.size[1]==56; const int count=channelsFirst?out.size[2]:out.size[1];
  if((channelsFirst?out.size[1]:out.size[2])!=56) throw std::runtime_error("Unsupported pose model: expected 56 channels (YOLOv8/11 pose)");
  if(out.type()!=CV_32F) throw std::runtime_error("Pose model must return float32");
  std::vector<cv::Rect> boxes;std::vector<float> scores;std::vector<Person> candidates;
  for(int i=0;i<count;i++) {
   auto val=[&](int k)->float {return channelsFirst?out.ptr<float>(0,k)[i]:out.ptr<float>(0,i)[k];};
   const float score=val(4);if(!std::isfinite(score)||score<settings_.confidence) continue;
   const double cx=(val(0)-ox)/scale,cy=(val(1)-oy)/scale,w=val(2)/scale,h=val(3)/scale;
   if(!std::isfinite(cx)||!std::isfinite(cy)||!std::isfinite(w)||!std::isfinite(h)||w<=1||h<=1)continue;
   cv::Rect box=cv::Rect(cv::Point(int(cx-w/2),int(cy-h/2)),cv::Size(int(w),int(h))) & cv::Rect(0,0,image.cols,image.rows);
   if(box.area()<=0)continue;
   Person p;p.box={double(box.x)/image.cols,double(box.y)/image.rows,double(box.width)/image.cols,double(box.height)/image.rows};p.score=score;
   for(int j=0;j<17;j++) {
    const float confidence=val(5+j*3+2);
    p.joints.emplace_back(confidence>.35f?float((val(5+j*3)-ox)/scale):-1.f,confidence>.35f?float((val(5+j*3+1)-oy)/scale):-1.f);
   }
   boxes.push_back(box);scores.push_back(score);candidates.push_back(std::move(p));
  }
  std::vector<int> kept;cv::dnn::NMSBoxes(boxes,scores,float(settings_.confidence),.45f,kept);
  for(int i:kept)persons.push_back(std::move(candidates.at(size_t(i))));
 } else {
  std::vector<cv::Rect> boxes;std::vector<double> scores;
  cv::Mat small;const double ratio=std::min(1.,960./std::max(image.cols,image.rows));
  cv::resize(image,small,cv::Size(),ratio,ratio);
  hog_.detectMultiScale(small,boxes,scores,0,cv::Size(8,8),cv::Size(16,16),1.05,2,false);
  for(size_t i=0;i<boxes.size();++i) {
   auto b=boxes[i];Person p;p.box={b.x/(ratio*image.cols),b.y/(ratio*image.rows),b.width/(ratio*image.cols),b.height/(ratio*image.rows)};
   p.score=float(std::clamp(scores[i],0.,1.));persons.push_back(std::move(p));
  }
 }
 return persons;
}
cv::Rect Pipeline::cropRect(View view,cv::Size source,cv::Size output) {
 const double aspect=double(output.width)/output.height,srcAspect=double(source.width)/source.height;
 const double fullW=std::min(double(source.width),source.height*aspect);
 const double fullH=fullW/aspect;
 int w=std::clamp(int(std::round(fullW/std::max(1.,view.zoom))),1,source.width);
 int h=std::clamp(int(std::round(fullH/std::max(1.,view.zoom))),1,source.height);
 // Match output aspect as closely as pixel quantization allows.
 if(w>=2&&h>=2){w=std::max(1,int(std::round(h*aspect)));if(w>source.width){w=source.width;h=std::max(1,int(std::round(w/aspect)));}}
 int x=std::clamp(int(std::round(view.cx*source.width-w/2.)),0,source.width-w);
 int y=std::clamp(int(std::round(view.cy*source.height-h/2.)),0,source.height-h);
 return {x,y,w,h};
}
FrameResult Pipeline::process(const cv::Mat& frame,double dt) {
 if(frame.empty()||frame.cols<=0||frame.rows<=0)throw std::invalid_argument("Empty input video frame");
 sourceAspect_=double(frame.cols)/frame.rows;
 FrameResult result;result.people=detect(frame);
 std::vector<Detection> ds;for(const auto& p:result.people)ds.push_back({p.box,std::max(.26f,p.score),0});
 if(pendingSelect_) {
  int best=-1;double area=1e9;
  for(size_t i=0;i<result.people.size();++i){const Rect b=result.people[i].box;auto pt=*pendingSelect_;
   if(pt.x>=b.x&&pt.x<=b.x+b.w&&pt.y>=b.y&&pt.y<=b.y+b.h&&b.w*b.h<area){area=b.w*b.h;best=int(i);}}
  if(best>=0)tracker_.select(result.people[size_t(best)].box);
  pendingSelect_.reset();
 }
 // Automatically acquire a person only if none has ever been selected.
 if(!tracker_.selected()&&!lastBox_&&!result.people.empty()) {
  auto it=std::max_element(result.people.begin(),result.people.end(),[](const Person& a,const Person& b){return a.box.w*a.box.h<b.box.w*b.box.h;});
  tracker_.select(it->box);
 }
 auto match=tracker_.update(ds);
 if(match) {lastBox_=*match;double best=0;for(size_t i=0;i<result.people.size();++i){double iou=intersectionOverUnion(*match,result.people[i].box);if(iou>best){best=iou;result.tracked=int(i);}}}
 else result.targetLost=tracker_.selected();
 if(match)lastView_=camera_.update(*match,double(frame.cols)/frame.rows,double(settings_.outputWidth)/settings_.outputHeight,std::max(0.,dt),settings_.occupancy);
 cv::Mat composed;cv::resize(frame(cropRect(lastView_,frame.size(),{settings_.outputWidth,settings_.outputHeight})),composed,{settings_.outputWidth,settings_.outputHeight});
 // Overlay on original coordinates before cropping for correct geometry.
 cv::Mat annotated=frame.clone();
 static const int links[][2]={{5,6},{5,7},{7,9},{6,8},{8,10},{5,11},{6,12},{11,12},{11,13},{13,15},{12,14},{14,16}};
 for(size_t i=0;i<result.people.size();++i) {
  const auto& p=result.people[i];cv::Scalar color=(int(i)==result.tracked)?cv::Scalar(40,220,40):cv::Scalar(0,190,255);
  cv::Rect b(int(p.box.x*frame.cols),int(p.box.y*frame.rows),int(p.box.w*frame.cols),int(p.box.h*frame.rows));cv::rectangle(annotated,b,color,2);
  if(settings_.drawSkeleton&&p.joints.size()==17){for(auto link:links){auto a=p.joints[size_t(link[0])],b2=p.joints[size_t(link[1])];if(a.x>=0&&b2.x>=0)cv::line(annotated,a,b2,color,2);}}
 }
 cv::resize(annotated(cropRect(lastView_,frame.size(),{settings_.outputWidth,settings_.outputHeight})),result.image,{settings_.outputWidth,settings_.outputHeight});
 return result;
}
}
