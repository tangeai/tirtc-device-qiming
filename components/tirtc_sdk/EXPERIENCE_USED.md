# Experience Used

1. Verify archive architecture and content hashes, not directory labels.
2. Copy all public headers with their library and rebuild dependent objects.
3. Check the real FreeRTOS 1000 Hz/trace/static-object ABI and retain guards.
4. Keep HTTPS policy separate from optional DTLS/media support; a package README
   cannot override the delivered binary's actual capability.
5. Preserve old SDK and APP recovery artifacts; keep each firmware's test
   evidence separate. Do not transplant old P4/SDIO/C61 tuning into this board.
