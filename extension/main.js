(() => {
  const installFix = () => {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices || mediaDevices.__nyxeosEnumerateDevicesPatched) {
      return;
    }

    const fallbackDevices = [
      {
        deviceId: "default",
        kind: "audioinput",
        label: "Microphone par défaut",
        groupId: "nyxeos-default-audio"
      },
      {
        deviceId: "default",
        kind: "audiooutput",
        label: "Sortie audio par défaut",
        groupId: "nyxeos-default-audio"
      }
    ];
    const originalEnumerateDevices = mediaDevices.enumerateDevices.bind(mediaDevices);

    mediaDevices.enumerateDevices = () => Promise.race([
      originalEnumerateDevices(),
      new Promise((resolve) => {
        window.setTimeout(() => resolve(fallbackDevices), 800);
      })
    ]);
    Object.defineProperty(mediaDevices, "__nyxeosEnumerateDevicesPatched", {
      value: true,
      configurable: false,
      enumerable: false,
      writable: false
    });
  };

  installFix();
})();
