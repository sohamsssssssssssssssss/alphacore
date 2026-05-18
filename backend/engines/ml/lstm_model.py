from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class _LSTMNet(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, num_layers: int, output_dim: int):
        super().__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers=num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        return self.fc(last)


class LSTMModel:
    def __init__(self, input_dim, hidden_dim=64, num_layers=2, output_dim=3):
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.num_layers = int(num_layers)
        self.output_dim = int(output_dim)
        self.model = _LSTMNet(self.input_dim, self.hidden_dim, self.num_layers, self.output_dim)
        self._device = torch.device("cpu")
        self.model.to(self._device)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.model(x)

    def fit(self, X: np.ndarray, y: np.ndarray, epochs=10, lr=1e-3):
        Xn = np.asarray(X, dtype=np.float32)
        yn = np.asarray(y, dtype=np.int64)
        if Xn.ndim == 2:
            Xn = Xn[:, None, :]

        ds = TensorDataset(torch.from_numpy(Xn), torch.from_numpy(yn))
        loader = DataLoader(ds, batch_size=min(64, len(ds)), shuffle=True)

        criterion = nn.CrossEntropyLoss()
        optim = torch.optim.Adam(self.model.parameters(), lr=float(lr))

        self.model.train()
        for _ in range(int(epochs)):
            for xb, yb in loader:
                xb = xb.to(self._device)
                yb = yb.to(self._device)
                optim.zero_grad()
                logits = self.model(xb)
                loss = criterion(logits, yb)
                loss.backward()
                optim.step()

    def predict(self, X: np.ndarray) -> np.ndarray:
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        Xn = np.asarray(X, dtype=np.float32)
        if Xn.ndim == 2:
            Xn = Xn[:, None, :]
        self.model.eval()
        with torch.no_grad():
            logits = self.model(torch.from_numpy(Xn).to(self._device))
            probs = torch.softmax(logits, dim=1).cpu().numpy()
        return probs

    def save(self, path: str):
        payload = {
            "state_dict": self.model.state_dict(),
            "input_dim": self.input_dim,
            "hidden_dim": self.hidden_dim,
            "num_layers": self.num_layers,
            "output_dim": self.output_dim,
        }
        torch.save(payload, path)

    def load(self, path: str):
        payload = torch.load(path, map_location=self._device)
        self.input_dim = int(payload["input_dim"])
        self.hidden_dim = int(payload["hidden_dim"])
        self.num_layers = int(payload["num_layers"])
        self.output_dim = int(payload["output_dim"])
        self.model = _LSTMNet(self.input_dim, self.hidden_dim, self.num_layers, self.output_dim)
        self.model.load_state_dict(payload["state_dict"])
        self.model.to(self._device)
