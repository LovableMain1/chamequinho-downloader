import { useState, useRef, ChangeEvent } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Upload, Download, Grid3x3, Image as ImageIcon, X, FileDown, FileImage } from 'lucide-react';
import { useToast } from '@/hooks/use-toast';
import { cn } from '@/lib/utils';
import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

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
      title: "Gerando imagem HD...",
      description: "Aguarde um momento.",
    });

    try {
      const gridElement = gridRef.current;

      // Enhanced html2canvas options for maximum quality
      const canvas = await html2canvas(gridElement, {
        scale: scale,
        backgroundColor: '#ffffff',
        logging: false,
        useCORS: true,
        allowTaint: false,
        imageTimeout: 0,
        removeContainer: false,
        foreignObjectRendering: false,
        width: gridElement.offsetWidth,
        height: gridElement.offsetHeight,
        scrollX: 0,
        scrollY: 0,
      });

      canvas.toBlob((blob) => {
        if (blob) {
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
          link.download = `chamequinho-HD-${gridSize.rows}x${gridSize.cols}-${quality}-${timestamp}.png`;
          link.click();
          URL.revokeObjectURL(url);
          toast({
            title: "Sucesso HD!",
            description: `Imagem salva em qualidade ${quality} (${(blob.size / (1024 * 1024)).toFixed(1)}MB)`,
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

  const downloadAsPDF = async (scale: number, quality: string) => {
    if (!gridRef.current) return;

    toast({
      title: "Gerando PDF...",
      description: "Aguarde um momento.",
    });

    try {
      const gridElement = gridRef.current;

      // Enhanced html2canvas options for maximum quality
      const canvas = await html2canvas(gridElement, {
        scale: scale,
        backgroundColor: '#ffffff',
        logging: false,
        useCORS: true,
        allowTaint: false,
        imageTimeout: 0,
        removeContainer: false,
        foreignObjectRendering: false,
        width: gridElement.offsetWidth,
        height: gridElement.offsetHeight,
        scrollX: 0,
        scrollY: 0,
      });

      const imgData = canvas.toDataURL('image/png', 1.0);
      const imgWidth = canvas.width;
      const imgHeight = canvas.height;

      // Calculate PDF dimensions (A4 or custom)
      const pdf = new jsPDF({
        orientation: imgWidth > imgHeight ? 'landscape' : 'portrait',
        unit: 'px',
        format: [imgWidth / scale, imgHeight / scale],
      });

      // Add image to PDF
      pdf.addImage(imgData, 'PNG', 0, 0, imgWidth / scale, imgHeight / scale, undefined, 'FAST');

      const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
      pdf.save(`chamequinho-HD-${gridSize.rows}x${gridSize.cols}-${quality}-${timestamp}.pdf`);

      toast({
        title: "Sucesso PDF!",
        description: `PDF salvo em qualidade ${quality}`,
      });
    } catch (error) {
      toast({
        title: "Erro",
        description: "Não foi possível gerar o PDF.",
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
                    "relative rounded-lg overflow-hidden transition-all border-2",
                    photo ? "border-primary/60" : "border-border/40",
                    "hover:border-primary hover:shadow-md cursor-pointer",
                    objectFit === 'contain' ? 'bg-slate-50' : 'bg-white'
                  )}
                  onClick={() => handleSlotClick(index)}
                >
                  {photo ? (
                    <img
                      src={photo.url}
                      alt=""
                      className="w-full h-full"
                      style={{ 
                        objectFit,
                        background: objectFit === 'contain' ? '#f8fafc' : 'transparent'
                      }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-muted-foreground bg-gradient-to-br from-slate-50 to-slate-100">
                      <ImageIcon className="w-8 h-8 opacity-30" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="glass p-6">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            <Download className="w-5 h-5 text-primary" />
            Download em Alta Qualidade
          </h2>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="space-y-3">
              <div className="flex items-center gap-2 mb-2">
                <FileImage className="w-4 h-4 text-primary" />
                <p className="text-sm font-semibold">Download como Imagem PNG</p>
              </div>
              <div className="flex flex-col gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsImage(2, 'media')}
                  className="w-full justify-start"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Qualidade Média (2x)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsImage(3, 'alta')}
                  className="w-full justify-start"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Qualidade Alta (3x)
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => downloadAsImage(4, 'ultra')}
                  className="w-full justify-start"
                >
                  <Download className="w-4 h-4 mr-2" />
                  Qualidade Ultra HD (4x)
                </Button>
              </div>
            </div>
            
            <div className="space-y-3">
              <div className="flex items-center gap-2 mb-2">
                <FileDown className="w-4 h-4 text-primary" />
                <p className="text-sm font-semibold">Download como PDF</p>
              </div>
              <div className="flex flex-col gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsPDF(2, 'media')}
                  className="w-full justify-start"
                >
                  <FileDown className="w-4 h-4 mr-2" />
                  PDF Média (2x)
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => downloadAsPDF(3, 'alta')}
                  className="w-full justify-start"
                >
                  <FileDown className="w-4 h-4 mr-2" />
                  PDF Alta (3x)
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => downloadAsPDF(4, 'ultra')}
                  className="w-full justify-start"
                >
                  <FileDown className="w-4 h-4 mr-2" />
                  PDF Ultra HD (4x)
                </Button>
              </div>
            </div>
          </div>
          <div className="mt-4 p-3 bg-primary/5 border border-primary/20 rounded-lg">
            <p className="text-xs text-muted-foreground">
              💡 <strong>Dica:</strong> As bordas são mantidas no download para facilitar o recorte de cada logo. Qualidade Ultra HD (4x) oferece a melhor resolução para impressão profissional.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
};
