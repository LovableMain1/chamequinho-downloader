import { useState, useRef, ChangeEvent } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Upload, Download, Grid3x3, Image as ImageIcon, X, FileDown } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';

interface PhotoItem {
  id: string;
  url: string;
}

export const PhotoGrid = () => {
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [gridSize, setGridSize] = useState({ rows: 3, cols: 3 });
  const [selectedSlots, setSelectedSlots] = useState<Record<number, PhotoItem | null>>({});
  const [objectFit, setObjectFit] = useState<'cover' | 'contain'>('contain');
  const [dragActive, setDragActive] = useState(false);
  const gridRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    
    const newPhotos: PhotoItem[] = [];
    Array.from(files).forEach(file => {
      if (file.type.startsWith('image/')) {
        newPhotos.push({
          id: Math.random().toString(36).substring(7),
          url: URL.createObjectURL(file),
        });
      }
    });
    
    if (newPhotos.length > 0) {
      setPhotos(prev => [...prev, ...newPhotos]);
      toast({
        title: "Fotos adicionadas!",
        description: `${newPhotos.length} foto(s) carregada(s).`,
      });
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files);
  };

  const handleSlotClick = (index: number) => {
    if (photos.length === 0) return;
    
    const currentPhoto = selectedSlots[index];
    if (currentPhoto) {
      const currentIndex = photos.findIndex(p => p.id === currentPhoto.id);
      const nextIndex = (currentIndex + 1) % photos.length;
      setSelectedSlots(prev => ({
        ...prev,
        [index]: photos[nextIndex]
      }));
    } else {
      setSelectedSlots(prev => ({
        ...prev,
        [index]: photos[0]
      }));
    }
  };

  const handleRemovePhoto = (id: string) => {
    setPhotos(prev => prev.filter(p => p.id !== id));
    setSelectedSlots(prev => {
      const newSlots = { ...prev };
      Object.keys(newSlots).forEach(key => {
        if (newSlots[Number(key)]?.id === id) {
          delete newSlots[Number(key)];
        }
      });
      return newSlots;
    });
  };

  const downloadAsImage = async (scale: number, quality: string) => {
    if (!gridRef.current) return;

    toast({
      title: "Gerando imagem...",
      description: "Aguarde um momento.",
    });

    try {
      const gridElement = gridRef.current;
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Canvas not supported');

      const rect = gridElement.getBoundingClientRect();
      canvas.width = rect.width * scale;
      canvas.height = rect.height * scale;
      ctx.scale(scale, scale);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, rect.width, rect.height);

      const slots = gridElement.querySelectorAll('[data-slot]');
      const gap = 8;
      const padding = 24;
      const cellWidth = (rect.width - padding * 2 - gap * (gridSize.cols - 1)) / gridSize.cols;
      const cellHeight = (rect.height - padding * 2 - gap * (gridSize.rows - 1)) / gridSize.rows;

      await Promise.all(
        Array.from(slots).map((slot, index) => {
          return new Promise<void>((resolve) => {
            const img = slot.querySelector('img');
            if (!img || !img.src) {
              resolve();
              return;
            }

            const image = new Image();
            image.crossOrigin = 'anonymous';
            image.onload = () => {
              const col = index % gridSize.cols;
              const row = Math.floor(index / gridSize.cols);
              const x = padding + col * (cellWidth + gap);
              const y = padding + row * (cellHeight + gap);

              ctx.save();
              ctx.beginPath();
              ctx.roundRect(x, y, cellWidth, cellHeight, 8);
              ctx.clip();

              if (objectFit === 'cover') {
                const scale = Math.max(cellWidth / image.width, cellHeight / image.height);
                const scaledW = image.width * scale;
                const scaledH = image.height * scale;
                const offsetX = x + (cellWidth - scaledW) / 2;
                const offsetY = y + (cellHeight - scaledH) / 2;
                ctx.drawImage(image, offsetX, offsetY, scaledW, scaledH);
              } else {
                const scale = Math.min(cellWidth / image.width, cellHeight / image.height);
                const scaledW = image.width * scale;
                const scaledH = image.height * scale;
                const offsetX = x + (cellWidth - scaledW) / 2;
                const offsetY = y + (cellHeight - scaledH) / 2;
                ctx.fillStyle = '#f8fafc';
                ctx.fillRect(x, y, cellWidth, cellHeight);
                ctx.drawImage(image, offsetX, offsetY, scaledW, scaledH);
              }

              ctx.restore();
              resolve();
            };
            image.onerror = () => resolve();
            image.src = img.src;
          });
        })
      );

      canvas.toBlob((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = `chamequinho-${quality}-${Date.now()}.png`;
          link.click();
          URL.revokeObjectURL(url);
          toast({
            title: "Sucesso!",
            description: `Imagem salva em qualidade ${quality}.`,
          });
        }
      }, 'image/png', 1.0);
    } catch (error) {
      toast({
        title: "Erro",
        description: "Não foi possível gerar a imagem.",
        variant: "destructive",
      });
    }
  };

  const totalSlots = gridSize.rows * gridSize.cols;

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-7xl mx-auto space-y-8">
        <div className="text-center space-y-4">
          <div className="flex items-center justify-center gap-3">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-primary-glow flex items-center justify-center shadow-lg">
              <Grid3x3 className="w-7 h-7 text-primary-foreground" />
            </div>
            <h1 className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-primary via-primary-glow to-secondary bg-clip-text text-transparent">
              Chamequinho Pro
            </h1>
          </div>
          <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
            Crie colagens profissionais com grid personalizável e download em alta qualidade
          </p>
        </div>

        <Card className="glass overflow-hidden border-2">
          <div
            onDragEnter={handleDrag}
            onDragLeave={handleDrag}
            onDragOver={handleDrag}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={cn(
              "p-12 text-center cursor-pointer transition-all duration-300",
              "border-3 border-dashed border-border rounded-lg",
              "hover:border-primary hover:bg-primary/5",
              dragActive && "border-primary bg-primary/10 scale-[1.02]"
            )}
          >
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept="image/*"
              onChange={handleChange}
              className="hidden"
            />
            <div className="space-y-4">
              <div className="mx-auto w-20 h-20 rounded-full bg-gradient-to-br from-primary to-secondary flex items-center justify-center shadow-lg">
                <Upload className="w-10 h-10 text-white" />
              </div>
              <div>
                <p className="text-xl font-semibold mb-2">
                  {dragActive ? "Solte as fotos aqui!" : "Arraste fotos ou clique para selecionar"}
                </p>
                <p className="text-muted-foreground">
                  Suporta PNG, JPG, JPEG e WEBP
                </p>
              </div>
            </div>
          </div>
        </Card>

        {photos.length > 0 && (
          <Card className="glass p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-primary" />
                Suas Fotos ({photos.length})
              </h2>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setPhotos([]);
                  setSelectedSlots({});
                }}
              >
                Limpar Todas
              </Button>
            </div>
            <div className="grid grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3">
              {photos.map((photo) => (
                <div key={photo.id} className="relative group">
                  <div className="aspect-square rounded-lg overflow-hidden border-2 border-border hover:border-primary transition-colors cursor-pointer">
                    <img
                      src={photo.url}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <button
                    onClick={() => handleRemovePhoto(photo.id)}
                    className="absolute -top-2 -right-2 w-6 h-6 bg-destructive text-destructive-foreground rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-lg"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card className="glass p-6 space-y-6">
          <h2 className="text-xl font-bold">Configurações do Grid</h2>
          
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <label className="text-sm font-medium">
                Linhas: {gridSize.rows}
              </label>
              <input
                type="range"
                min="2"
                max="6"
                value={gridSize.rows}
                onChange={(e) => setGridSize(prev => ({ ...prev, rows: parseInt(e.target.value) }))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>
            
            <div className="space-y-3">
              <label className="text-sm font-medium">
                Colunas: {gridSize.cols}
              </label>
              <input
                type="range"
                min="2"
                max="6"
                value={gridSize.cols}
                onChange={(e) => setGridSize(prev => ({ ...prev, cols: parseInt(e.target.value) }))}
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
            </div>
          </div>

          <div className="space-y-3">
            <label className="text-sm font-medium">Ajuste de Imagem</label>
            <div className="flex gap-3">
              <Button
                variant={objectFit === 'contain' ? 'default' : 'outline'}
                onClick={() => setObjectFit('contain')}
                className="flex-1"
              >
                Conter
              </Button>
              <Button
                variant={objectFit === 'cover' ? 'default' : 'outline'}
                onClick={() => setObjectFit('cover')}
                className="flex-1"
              >
                Preencher
              </Button>
            </div>
          </div>
        </Card>

        <Card className="glass p-8">
          <div
            ref={gridRef}
            className="bg-white p-6 rounded-xl shadow-lg mx-auto max-w-4xl"
            style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${gridSize.cols}, 1fr)`,
              gridTemplateRows: `repeat(${gridSize.rows}, 1fr)`,
              gap: '8px',
              aspectRatio: `${gridSize.cols} / ${gridSize.rows}`
            }}
          >
            {Array.from({ length: totalSlots }).map((_, index) => {
              const photo = selectedSlots[index];
              return (
                <div
                  key={index}
                  data-slot={index}
                  className={cn(
                    "relative border-2 rounded-lg overflow-hidden transition-all",
                    photo ? "border-primary" : "border-border bg-surface-variant",
                    "hover:border-primary hover:shadow-md cursor-pointer"
                  )}
                  onClick={() => handleSlotClick(index)}
                >
                  {photo ? (
                    <img
                      src={photo.url}
                      alt=""
                      className="w-full h-full"
                      style={{ objectFit }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                      <ImageIcon className="w-8 h-8 opacity-30" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="glass p-6">
          <h2 className="text-xl font-bold mb-4">Download</h2>
          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-3">
              <p className="text-sm font-medium">Baixar como Imagem</p>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsImage(1, 'baixa')}
                  className="flex-1"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Baixa
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsImage(2, 'media')}
                  className="flex-1"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Média
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsImage(3, 'alta')}
                  className="flex-1"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Alta
                </Button>
              </div>
            </div>
            
            <div className="space-y-3">
              <p className="text-sm font-medium">Nota sobre PDF</p>
              <p className="text-xs text-muted-foreground">
                Após o download, você pode converter a imagem em PDF usando ferramentas online ou impressoras virtuais.
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};
