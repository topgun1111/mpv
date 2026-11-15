package ai.onnxruntime;
import java.nio.*;
public class OnnxTensor implements OnnxValue {
  public static OnnxTensor createTensor(OrtEnvironment e, FloatBuffer b, long[] s) throws OrtException { return null; }
  public static OnnxTensor createTensor(OrtEnvironment e, IntBuffer b, long[] s) throws OrtException { return null; }
  public static OnnxTensor createTensor(OrtEnvironment e, LongBuffer b, long[] s) throws OrtException { return null; }
  public static OnnxTensor createTensor(OrtEnvironment e, ByteBuffer b, long[] s, OnnxJavaType t) throws OrtException { return null; }
  public static OnnxTensor createTensor(OrtEnvironment e, Object o) throws OrtException { return null; }
  public FloatBuffer getFloatBuffer(){return null;}
  public Object getValue() throws OrtException {return null;}
  public TensorInfo getInfo(){return null;}
  public void close(){}
}
