use serde::Deserialize;
use std::sync::Mutex;
use std::time::{Duration, SystemTime};
use tracing::{info, warn};

/// Shared Google Cloud Platform client for auth and storage.
pub struct GcpClient {
    /// Cached access token + expiry
    token_cache: Mutex<Option<CachedToken>>,
}

struct CachedToken {
    access_token: String,
    expires_at: SystemTime,
}

#[derive(Deserialize)]
struct MetadataTokenResponse {
    access_token: String,
    expires_in: u64,
}

impl Default for GcpClient {
    fn default() -> Self {
        Self::new()
    }
}

impl GcpClient {
    pub fn new() -> Self {
        Self {
            token_cache: Mutex::new(None),
        }
    }

    /// Get an access token from the Cloud Run metadata server.
    pub fn get_access_token(&self) -> Option<String> {
        // Check cache first
        if let Ok(cache) = self.token_cache.lock() {
            if let Some(ref cached) = *cache {
                if SystemTime::now() < cached.expires_at {
                    return Some(cached.access_token.clone());
                }
            }
        }

        // Try Cloud Run metadata server (automatic identity on GCP)
        let token_info = ureq::get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        )
        .set("Metadata-Flavor", "Google")
        .call()
        .ok()?
        .into_json::<MetadataTokenResponse>()
        .ok()?;

        let expires_at = SystemTime::now() + Duration::from_secs(token_info.expires_in.saturating_sub(60));

        if let Ok(mut cache) = self.token_cache.lock() {
            *cache = Some(CachedToken {
                access_token: token_info.access_token.clone(),
                expires_at,
            });
        }

        Some(token_info.access_token)
    }

    /// Simple media upload to Google Cloud Storage.
    pub fn upload_to_gcs(&self, bucket: &str, object_name: &str, content: &[u8]) -> anyhow::Result<()> {
        let token = self.get_access_token()
            .ok_or_else(|| anyhow::anyhow!("Failed to get GCP access token"))?;

        // Simple media upload URL
        // GCS requires the object name to be URL-encoded in the query param
        let encoded_name = object_name.replace('/', "%2F").replace(' ', "%20");
        let url = format!(
            "https://storage.googleapis.com/upload/storage/v1/b/{}/o?uploadType=media&name={}",
            bucket,
            encoded_name
        );

        let resp = ureq::post(&url)
            .set("Authorization", &format!("Bearer {}", token))
            .set("Content-Type", "application/json")
            .send_bytes(content)?;

        if resp.status() >= 400 {
            let error_text = resp.into_string().unwrap_or_else(|_| "unknown error".into());
            warn!(bucket = %bucket, object = %object_name, error = %error_text, "GCS upload failed");
            anyhow::bail!("GCS upload failed: {}", error_text);
        }

        info!(bucket = %bucket, object = %object_name, "GCS upload successful");
        Ok(())
    }
}
