use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    os::fd::AsRawFd,
    os::unix::net::UnixStream,
    time::Duration,
};

const SOCKET: &str = "/run/deckport-vpn/control.sock";
const PROTOCOL_VERSION: i64 = 1;
const MAX_RESPONSE: usize = 2 * 1024 * 1024;

fn verify_server(stream: &UnixStream) -> Result<(), String> {
    let mut credentials: libc::ucred =
        unsafe { std::mem::zeroed() };

    let mut length =
        std::mem::size_of::<libc::ucred>() as libc::socklen_t;

    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            &mut credentials as *mut _ as *mut libc::c_void,
            &mut length,
        )
    };

    if result != 0 {
        return Err(
            "Could not verify DeckPort service identity".into()
        );
    }

    if credentials.uid != 0 {
        return Err(
            "DeckPort service identity check failed".into()
        );
    }

    Ok(())
}

pub fn call(
    method: &str,
    args: Vec<Value>,
) -> Result<Value, String> {
    let mut stream = UnixStream::connect(SOCKET)
        .map_err(|_| "DeckPort service is unavailable".to_string())?;

    stream
        .set_read_timeout(Some(Duration::from_secs(100)))
        .map_err(|_| "Could not configure service connection".to_string())?;

    stream
        .set_write_timeout(Some(Duration::from_secs(10)))
        .map_err(|_| "Could not configure service connection".to_string())?;

    verify_server(&stream)?;

    let request = json!({
        "version": PROTOCOL_VERSION,
        "method": method,
        "args": args,
    });

    let encoded = serde_json::to_vec(&request)
        .map_err(|_| "Could not encode control request".to_string())?;

    stream
        .write_all(&encoded)
        .and_then(|_| stream.write_all(b"\n"))
        .map_err(|_| "Could not send control request".to_string())?;

    let mut reader = BufReader::new(stream);
    let mut response = Vec::new();

    let count = reader
        .read_until(b'\n', &mut response)
        .map_err(|_| "Could not read service response".to_string())?;

    if count == 0
        || count > MAX_RESPONSE
        || response.last() != Some(&b'\n')
    {
        return Err(
            "Invalid DeckPort service response".into()
        );
    }

    let value: Value = serde_json::from_slice(&response)
        .map_err(|_| "Invalid DeckPort service response".to_string())?;

    if value.get("version").and_then(Value::as_i64)
        != Some(PROTOCOL_VERSION)
    {
        return Err(
            "Incompatible DeckPort service; reinstall DeckPort VPN".into()
        );
    }

    match value.get("ok").and_then(Value::as_bool) {
        Some(true) => Ok(
            value.get("data").cloned().unwrap_or(Value::Null)
        ),
        Some(false) => Err(
            value
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Operation failed")
                .to_string()
        ),
        None => Err(
            "Invalid DeckPort service response".into()
        ),
    }
}
