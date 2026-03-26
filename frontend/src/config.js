const BASE = import.meta.env.VITE_API_BASE_URL || ''

export const API = {
  generate:                `${BASE}/api/generate`,
  generateStop:            `${BASE}/api/generate/stop`,
  code:        (v)    =>   `${BASE}/api/code/${v}`,
  codeStop:                `${BASE}/api/code/stop`,
  versions:                `${BASE}/api/versions`,
  version:     (v)    =>   `${BASE}/api/versions/${v}`,
  queueStatus: (v)    =>   `${BASE}/api/versions/${v}/queue`,
  queueRetry:  (v)    =>   `${BASE}/api/versions/${v}/queue/retry`,
  equations:   (v)    =>   `${BASE}/api/versions/${v}/equations`,
  equationFile:(v, f) =>   `${BASE}/api/versions/${v}/equations/${f}`,
  java:        (v)    =>   `${BASE}/api/versions/${v}/java`,
  javaFile:    (v, f) =>   `${BASE}/api/versions/${v}/java/${f}`,
  javaZip:          (v)    =>   `${BASE}/api/versions/${v}/java-zip`,
  javaRegenerate:   (v)    =>   `${BASE}/api/versions/${v}/java/regenerate`,
  javaArchives:     (v)    =>   `${BASE}/api/versions/${v}/java-archives`,
  deleteVersion:(v)   =>   `${BASE}/api/versions/${v}`,
  policy:      (n)    =>   `${BASE}/api/policy/${n}`,
}
