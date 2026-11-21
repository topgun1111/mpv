#include "pipeline.hpp"
#include <QApplication>
#include <QCheckBox>
#include <QCloseEvent>
#include <QDateTime>
#include <QFile>
#include <QSysInfo>
#include <QResizeEvent>
#include <QPixmap>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QImage>
#include <QLabel>
#include <QMainWindow>
#include <QMessageBox>
#include <QMouseEvent>
#include <QMutex>
#include <QMutexLocker>
#include <QPlainTextEdit>
#include <QProcess>
#include <QPushButton>
#include <QSlider>
#include <QSpinBox>
#include <QStandardPaths>
#include <QStatusBar>
#include <QTextStream>
#include <QThread>
#include <QTimer>
#include <QVBoxLayout>
#include <atomic>
#include <exception>
#include <memory>
#include <opencv2/opencv.hpp>

namespace {
QMutex logMutex;
QString logPath;
void logLine(const QString& category,const QString& message) {
 QMutexLocker lock(&logMutex);
 QFile file(logPath);
 if(file.open(QIODevice::Append|QIODevice::Text)) {
  QTextStream out(&file);out<<QDateTime::currentDateTime().toString(Qt::ISODateWithMs)<<" ["<<category<<"] [thread="<<quintptr(QThread::currentThreadId())<<"] "<<message<<'\n';
 }
}
void qtLog(QtMsgType type,const QMessageLogContext& context,const QString& message) {
 const char* labels[]={"DEBUG","WARN","CRITICAL","FATAL","INFO"};
 QString s=message+QString(" [%1:%2 %3]").arg(context.file?context.file:"?").arg(context.line).arg(context.function?context.function:"?");
 logLine(labels[int(type)],s);
 if(type==QtFatalMsg)abort();
}
QImage toImage(const cv::Mat& bgr) {
 cv::Mat rgb;cv::cvtColor(bgr,rgb,cv::COLOR_BGR2RGB);
 return QImage(rgb.data,rgb.cols,rgb.rows,int(rgb.step),QImage::Format_RGB888).copy();
}
class VideoView:public QLabel {
public:
 std::function<void(double,double)> selected;
 explicit VideoView(QWidget* p=nullptr):QLabel(p){setAlignment(Qt::AlignCenter);setMinimumSize(640,360);setStyleSheet("background:#111827;color:#9ca3af;border-radius:8px;");setText("Open a video to begin");}
 void showFrame(const QImage& image){current_=image;updateFrame();}
protected:
 void resizeEvent(QResizeEvent* e)override{QLabel::resizeEvent(e);updateFrame();}
 void mousePressEvent(QMouseEvent* e)override {
  if(current_.isNull()||!selected)return;
  QSize fitted=current_.size();fitted.scale(size(),Qt::KeepAspectRatio);
  QPointF origin((width()-fitted.width())/2.,(height()-fitted.height())/2.);
  QPointF p=e->position()-origin;
  if(p.x()>=0&&p.y()>=0&&p.x()<fitted.width()&&p.y()<fitted.height())selected(p.x()/fitted.width(),p.y()/fitted.height());
 }
private:
 QImage current_;
 void updateFrame(){if(!current_.isNull())setPixmap(QPixmap::fromImage(current_).scaled(size(),Qt::KeepAspectRatio,Qt::SmoothTransformation));}
};
class ExportWorker:public QThread {
public:
 QString source,destination,model;native::Settings settings;std::atomic_bool cancel{false};
 std::function<void(int)> progress;std::function<void(QString)> finished;
 void run()override{
  QString error;
  try {
   cv::VideoCapture input(source.toStdString());if(!input.isOpened())throw std::runtime_error("Cannot open input video");
   double fps=input.get(cv::CAP_PROP_FPS);if(!(fps>0&&fps<240))fps=30;
   native::Pipeline pipeline(settings);std::string modelError;
   if(!pipeline.loadModel(model.toStdString(),modelError))throw std::runtime_error("Model load: "+modelError);
   logLine("INFO",QString("EXPORT start source=%1 output=%2 fps=%3 model=%4 backend=%5").arg(source,destination).arg(fps).arg(model,pipeline.backend()));
   // Write to temporary file; never replace a valid destination on failure.
   QString temporary=destination+".partial.mp4";
   cv::VideoWriter writer(temporary.toStdString(),cv::VideoWriter::fourcc('m','p','4','v'),fps,cv::Size(settings.outputWidth,settings.outputHeight));
   if(!writer.isOpened())throw std::runtime_error("Cannot initialize MP4 video encoder");
   const double total=input.get(cv::CAP_PROP_FRAME_COUNT);cv::Mat frame;int index=0;
   while(!cancel.load()&&input.read(frame)) {
    auto output=pipeline.process(frame,1.0/fps);writer.write(output.image);++index;
    if(index%30==0){if(progress)progress(total>0?int(100.*index/total):0);logLine("DEBUG",QString("EXPORT frame=%1 total=%2 targetLost=%3 detections=%4").arg(index).arg(total).arg(output.targetLost).arg(output.people.size()));}
   }
   writer.release();input.release();
   if(cancel.load()) {QFile::remove(temporary);error="Export cancelled";}
   else if(index==0){QFile::remove(temporary);error="No frames decoded";}
   else {
    if(QFile::exists(destination)&&!QFile::remove(destination))throw std::runtime_error("Cannot overwrite destination");
    if(!QFile::rename(temporary,destination))throw std::runtime_error("Cannot rename completed video");
    logLine("INFO",QString("EXPORT success frames=%1 destination=%2 (video only; source audio not copied)").arg(index).arg(destination));
   }
  }catch(const cv::Exception& e){error=QString("OpenCV error: %1").arg(e.what());}
   catch(const std::exception& e){error=QString::fromUtf8(e.what());}
  if(!error.isEmpty())logLine("ERROR",QString("EXPORT failed: %1").arg(error));
  if(finished)finished(error);
 }
};
class MainWindow:public QMainWindow {
public:
 MainWindow(){
  setWindowTitle("Takipli Oynat — Windows Native");resize(1200,800);
  auto* center=new QWidget;auto* layout=new QVBoxLayout(center);
  auto* controls=new QHBoxLayout;
  auto* open=new QPushButton("Open video");auto* modelButton=new QPushButton("Load pose ONNX");
  play_=new QPushButton("Play");auto* exportButton=new QPushButton("Export MP4");auto* cancelButton=new QPushButton("Cancel export");
  controls->addWidget(open);controls->addWidget(modelButton);controls->addWidget(play_);controls->addWidget(exportButton);controls->addWidget(cancelButton);layout->addLayout(controls);
  view_=new VideoView;layout->addWidget(view_,1);
  auto* options=new QHBoxLayout;auto* occupancy=new QSlider(Qt::Horizontal);occupancy->setRange(35,95);occupancy->setValue(70);
  options->addWidget(new QLabel("Target occupancy"));options->addWidget(occupancy);
  auto* skeleton=new QCheckBox("Skeleton overlay");skeleton->setChecked(true);options->addWidget(skeleton);
  auto* output=new QSpinBox;output->setRange(360,2160);output->setSingleStep(180);output->setValue(720);options->addWidget(new QLabel("Output height"));options->addWidget(output);layout->addLayout(options);
  info_=new QLabel("No video loaded");layout->addWidget(info_);
  setCentralWidget(center);statusBar()->showMessage("Logs: "+logPath);
  timer_.setTimerType(Qt::PreciseTimer);
  connect(open,&QPushButton::clicked,this,[this]{openVideo();});
  connect(modelButton,&QPushButton::clicked,this,[this]{QString f=QFileDialog::getOpenFileName(this,"YOLO pose ONNX model",{},"ONNX models (*.onnx)");if(f.isEmpty())return;model_=f;rebuildPipeline();});
  connect(play_,&QPushButton::clicked,this,[this]{if(!capture_.isOpened())return;playing_=!playing_;play_->setText(playing_?"Pause":"Play");if(playing_)timer_.start(std::max(1,int(1000./fps_)));else timer_.stop();});
  connect(&timer_,&QTimer::timeout,this,[this]{nextFrame();});
  connect(occupancy,&QSlider::valueChanged,this,[this](int value){settings_.occupancy=value/100.;rebuildPipeline();});
  connect(skeleton,&QCheckBox::toggled,this,[this](bool enabled){settings_.drawSkeleton=enabled;rebuildPipeline();});
  connect(output,qOverload<int>(&QSpinBox::valueChanged),this,[this](int height){settings_.outputHeight=height;settings_.outputWidth=height*16/9;rebuildPipeline();});
  view_->selected=[this](double x,double y){if(pipeline_){pipeline_->select(x,y);logLine("INFO",QString("Target selection x=%1 y=%2").arg(x).arg(y));}};
  connect(exportButton,&QPushButton::clicked,this,[this]{startExport();});
  connect(cancelButton,&QPushButton::clicked,this,[this]{if(export_)export_->cancel=true;});
  logLine("INFO","Main window initialized");
 }
 ~MainWindow()override {timer_.stop();if(export_){export_->cancel=true;export_->wait();}}
private:
 VideoView* view_{};QPushButton* play_{};QLabel* info_{};QTimer timer_;
 cv::VideoCapture capture_;std::unique_ptr<native::Pipeline> pipeline_;ExportWorker* export_{};
 QString source_,model_;native::Settings settings_;double fps_=30;bool playing_=false;int frameNo_=0;
 void rebuildPipeline(){
  try {pipeline_=std::make_unique<native::Pipeline>(settings_);std::string error;
   if(!pipeline_->loadModel(model_.toStdString(),error)){logLine("ERROR","Model load: "+QString::fromStdString(error));QMessageBox::warning(this,"Model load failed",QString::fromStdString(error));model_.clear();pipeline_->loadModel("",error);}
   logLine("INFO",QString("Pipeline ready backend=%1 output=%2x%3").arg(QString::fromStdString(pipeline_->backend())).arg(settings_.outputWidth).arg(settings_.outputHeight));
  }catch(const std::exception& e){logLine("ERROR",e.what());QMessageBox::critical(this,"Pipeline error",e.what());}
 }
 void openVideo(){QString file=QFileDialog::getOpenFileName(this,"Open video",{},"Videos (*.mp4 *.mkv *.avi *.mov *.webm);;All files (*)");if(file.isEmpty())return;
  timer_.stop();playing_=false;play_->setText("Play");capture_.release();
  if(!capture_.open(file.toStdString())){logLine("ERROR","Video open failed: "+file);QMessageBox::warning(this,"Video error","Cannot decode this video.");return;}
  source_=file;fps_=capture_.get(cv::CAP_PROP_FPS);if(!(fps_>0&&fps_<240))fps_=30;frameNo_=0;rebuildPipeline();
  logLine("INFO",QString("Video opened file=%1 fps=%2 width=%3 height=%4 frames=%5").arg(file).arg(fps_).arg(capture_.get(cv::CAP_PROP_FRAME_WIDTH)).arg(capture_.get(cv::CAP_PROP_FRAME_HEIGHT)).arg(capture_.get(cv::CAP_PROP_FRAME_COUNT)));
  nextFrame();
 }
 void nextFrame(){try {
  if(!pipeline_||!capture_.isOpened())return;cv::Mat frame;
  if(!capture_.read(frame)){timer_.stop();playing_=false;play_->setText("Play");logLine("INFO",QString("Playback ended at frame=%1").arg(frameNo_));return;}
  auto result=pipeline_->process(frame,1.0/fps_);view_->showFrame(toImage(result.image));++frameNo_;
  info_->setText(QString("Frame %1 | People: %2 | Target: %3 | %4").arg(frameNo_).arg(result.people.size()).arg(result.targetLost?"lost":result.tracked>=0?"tracked":"none").arg(QString::fromStdString(pipeline_->backend())));
  if(frameNo_%60==0)logLine("DEBUG",QString("PREVIEW frame=%1 people=%2 tracked=%3 lost=%4").arg(frameNo_).arg(result.people.size()).arg(result.tracked).arg(result.targetLost));
 }catch(const cv::Exception& e){fail(e.what());}catch(const std::exception& e){fail(e.what());}}
 void fail(const QString& error){timer_.stop();playing_=false;play_->setText("Play");logLine("ERROR","Playback: "+error);QMessageBox::critical(this,"Processing failed",error);}
 void startExport(){if(source_.isEmpty()||export_)return;QString path=QFileDialog::getSaveFileName(this,"Export processed video",QFileInfo(source_).absolutePath()+"/tracked.mp4","MP4 (*.mp4)");if(path.isEmpty())return;
  export_=new ExportWorker;export_->source=source_;export_->destination=path;export_->model=model_;export_->settings=settings_;
  export_->progress=[this](int n){QMetaObject::invokeMethod(this,[this,n]{statusBar()->showMessage(QString("Export: %1% | Log: %2").arg(n).arg(logPath));},Qt::QueuedConnection);};
  export_->finished=[this](QString error){QMetaObject::invokeMethod(this,[this,error]{if(error.isEmpty())QMessageBox::information(this,"Export complete","Video exported successfully. Audio is not included.");else QMessageBox::warning(this,"Export result",error);statusBar()->showMessage("Logs: "+logPath);},Qt::QueuedConnection);};
  connect(export_,&QThread::finished,this,[this]{export_->deleteLater();export_=nullptr;});
  export_->start();
 }
};
}
int main(int argc,char** argv){
 QApplication app(argc,argv);
 QString base=QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);QDir().mkpath(base+"/logs");
 logPath=base+"/logs/mpv-"+QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss")+".log";
 qInstallMessageHandler(qtLog);
 logLine("INFO",QString("START Qt=%1 OpenCV=%2 OS=%3 args=%4").arg(qVersion(),CV_VERSION,QSysInfo::prettyProductName(),app.arguments().join(" ")));
 try {MainWindow window;window.show();int result=app.exec();logLine("INFO",QString("EXIT code=%1").arg(result));return result;}
 catch(const std::exception& e){logLine("FATAL",e.what());QMessageBox::critical(nullptr,"Fatal error",e.what());return 1;}
}
