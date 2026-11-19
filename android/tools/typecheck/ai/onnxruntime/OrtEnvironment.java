package ai.onnxruntime;
import java.util.EnumSet;
public class OrtEnvironment implements AutoCloseable {
  public static OrtEnvironment getEnvironment(){return null;}
  public static EnumSet<OrtProvider> getAvailableProviders(){return null;}
  public OrtSession createSession(String path, OrtSession.SessionOptions o) throws OrtException {return null;}
  public OrtSession createSession(byte[] b, OrtSession.SessionOptions o) throws OrtException {return null;}
  public void close(){}
}
