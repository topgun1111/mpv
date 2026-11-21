#include "track_math.hpp"
#include <QApplication>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QLabel>
#include <QMainWindow>
#include <QMediaPlayer>
#include <QAudioOutput>
#include <QMessageBox>
#include <QProcess>
#include <QPushButton>
#include <QSlider>
#include <QStatusBar>
#include <QVBoxLayout>
#include <QVideoWidget>
#include <QWidget>
#include <QUrl>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QStandardPaths>
#include <QDir>
#include <cmath>

int main(int argc, char** argv) {
    QApplication app(argc,argv);
    QMainWindow window;
    window.setWindowTitle("Takipli Oynat — Native Qt/C++ (manual framing)");
    window.resize(1100,760);
    auto* central=new QWidget(&window);
    auto* layout=new QVBoxLayout(central);
    auto* video=new QVideoWidget(central);
    video->setMinimumSize(640,360);
    layout->addWidget(video,1);
    auto* player=new QMediaPlayer(&window);
    auto* audio=new QAudioOutput(&window);
    player->setAudioOutput(audio);
    player->setVideoOutput(video);
    auto* buttons=new QHBoxLayout();
    auto* open=new QPushButton("Open video",central);
    auto* play=new QPushButton("Play / Pause",central);
    auto* exportBtn=new QPushButton("Export manual crop",central);
    buttons->addWidget(open);buttons->addWidget(play);buttons->addWidget(exportBtn);
    layout->addLayout(buttons);
    auto* seek=new QSlider(Qt::Horizontal,central);
    seek->setRange(0,0);layout->addWidget(seek);
    auto* options=new QHBoxLayout();
    auto* zoom=new QDoubleSpinBox(central);
    zoom->setRange(1,8);zoom->setSingleStep(0.25);zoom->setValue(1.5);zoom->setPrefix("Zoom ");
    auto* cx=new QDoubleSpinBox(central);cx->setRange(0,1);cx->setSingleStep(0.05);cx->setValue(0.5);cx->setPrefix("Center X ");
    auto* cy=new QDoubleSpinBox(central);cy->setRange(0,1);cy->setSingleStep(0.05);cy->setValue(0.5);cy->setPrefix("Center Y ");
    options->addWidget(zoom);options->addWidget(cx);options->addWidget(cy);
    layout->addLayout(options);
    auto* info=new QLabel("Manual constant crop export. AI detection, pose tracking and animated crop preview are NOT implemented.",central);
    info->setWordWrap(true);layout->addWidget(info);
    window.setCentralWidget(central);
    QString source;
    QObject::connect(open,&QPushButton::clicked,&window,[&](){
        const auto path=QFileDialog::getOpenFileName(&window,"Select video",{},"Video (*.mp4 *.mkv *.mov *.avi *.webm);;All files (*)");
        if(path.isEmpty()) return;
        source=path;player->setSource(QUrl::fromLocalFile(path));player->play();
        window.statusBar()->showMessage(QFileInfo(path).fileName());
    });
    QObject::connect(play,&QPushButton::clicked,player,[&](){if(player->playbackState()==QMediaPlayer::PlayingState)player->pause();else player->play();});
    QObject::connect(player,&QMediaPlayer::durationChanged,seek,[&](qint64 ms){seek->setMaximum(static_cast<int>(std::min<qint64>(ms,INT_MAX)));});
    QObject::connect(player,&QMediaPlayer::positionChanged,seek,[&](qint64 ms){if(!seek->isSliderDown())seek->setValue(static_cast<int>(std::min<qint64>(ms,INT_MAX)));});
    QObject::connect(seek,&QSlider::sliderMoved,player,[&](int ms){player->setPosition(ms);});
    QObject::connect(player,&QMediaPlayer::errorOccurred,&window,[&](QMediaPlayer::Error,const QString& err){window.statusBar()->showMessage(err);});
    QObject::connect(exportBtn,&QPushButton::clicked,&window,[&](){
        if(source.isEmpty()){QMessageBox::warning(&window,"No video","Open a video first.");return;}
        const auto output=QFileDialog::getSaveFileName(&window,"Export MP4",QFileInfo(source).completeBaseName()+"_crop.mp4","MP4 (*.mp4)");
        if(output.isEmpty())return;
        if(QFileInfo(output).absoluteFilePath()==QFileInfo(source).absoluteFilePath()){QMessageBox::warning(&window,"Invalid output","Output must differ from source.");return;}
        const QString ffmpeg=QStandardPaths::findExecutable("ffmpeg");
        const QString ffprobe=QStandardPaths::findExecutable("ffprobe");
        if(ffmpeg.isEmpty()||ffprobe.isEmpty()){QMessageBox::warning(&window,"FFmpeg missing","Install FFmpeg and FFprobe on PATH.");return;}
        QProcess probe;
        probe.start(ffprobe,{"-v","error","-select_streams","v:0","-show_entries","stream=width,height","-of","csv=p=0:s=x",source});
        if(!probe.waitForFinished(15000)||probe.exitCode()!=0){QMessageBox::warning(&window,"Probe failed",QString::fromUtf8(probe.readAllStandardError()));return;}
        const auto dims=QString::fromUtf8(probe.readAllStandardOutput()).trimmed().split('x');
        if(dims.size()!=2){QMessageBox::warning(&window,"Probe failed","Invalid video dimensions.");return;}
        bool okW=false,okH=false;const int w=dims[0].toInt(&okW),h=dims[1].toInt(&okH);
        if(!okW||!okH||w<2||h<2){QMessageBox::warning(&window,"Probe failed","Invalid video dimensions.");return;}
        const int cw=std::max(2,(static_cast<int>(std::floor(w/zoom->value()))/2)*2);
        const int ch=std::max(2,(static_cast<int>(std::floor(h/zoom->value()))/2)*2);
        const int x=std::clamp(static_cast<int>(std::round(cx->value()*w-cw/2.0)),0,w-cw);
        const int y=std::clamp(static_cast<int>(std::round(cy->value()*h-ch/2.0)),0,h-ch);
        const QString filter=QString("crop=%1:%2:%3:%4,scale=%5:%6:flags=lanczos").arg(cw).arg(ch).arg(x).arg(y).arg(w).arg(h);
        auto* process=new QProcess(&window);
        exportBtn->setEnabled(false);
        QObject::connect(process,&QProcess::finished,&window,[&,process,output](int code,QProcess::ExitStatus status){
            exportBtn->setEnabled(true);
            if(status==QProcess::NormalExit&&code==0){window.statusBar()->showMessage("Export complete: "+output);QMessageBox::information(&window,"Export complete",output);}
            else QMessageBox::critical(&window,"Export failed",QString::fromUtf8(process->readAllStandardError()).right(4000));
            process->deleteLater();
        });
        QObject::connect(process,&QProcess::errorOccurred,&window,[&,process](QProcess::ProcessError){exportBtn->setEnabled(true);QMessageBox::critical(&window,"Export error",process->errorString());process->deleteLater();});
        process->start(ffmpeg,{"-hide_banner","-nostdin","-y","-i",source,"-vf",filter,"-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",output});
        window.statusBar()->showMessage("Exporting...");
    });
    window.statusBar()->showMessage("Native Qt video player / manual export");
    window.show();
    return app.exec();
}
