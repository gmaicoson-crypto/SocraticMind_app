import CoreTransferable
import MindCore
import UniformTypeIdentifiers

/// Consume the temporary provider URL inside the import closure; never retain it after transfer.
struct AvatarPhotoTransfer: Transferable {
    let prepared: PreparedAvatar

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            let file = received.file
            let worker = Task.detached(priority: .userInitiated) { try AvatarImageCodec.prepare(file) }
            let prepared = try await withTaskCancellationHandler {
                try await worker.value
            } onCancel: { worker.cancel() }
            try Task.checkCancellation()
            return AvatarPhotoTransfer(prepared: prepared)
        }
    }
}
